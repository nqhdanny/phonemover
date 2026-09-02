"""Migration engine — orchestrate backup -> parse -> write as one pipeline.

The engine ties together the modules built so far:
  device detection -> backup (core.backup) -> parse -> write (MTP / APK-asset)

It exposes a single run() that migrates the selected data types from an
already-created backup directory into a destination (media folder or APK
asset folder), reporting progress and collecting per-type results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.backup import BackupResult, backup_full
from core.manifest import find_by_domain, find_by_path, resolve_blob
from core.models import DATA_TYPES, DataType
from core.parse.bookmarks import write_bookmarks
from core.parse.calendar import write_ics
from core.parse.contacts import write_vcards
from core.parse.notes import write_notes, write_notes_json
from core.parse.photos import extract_photos, extract_videos
from core.parse.reminders import write_reminders
from core.write.mtp import copy_media_tree

ProgressCB = Callable[[int, str, str], None]  # (percent 0-100, stage, message)


@dataclass
class TypeResult:
    data_type: DataType
    ok: bool
    count: int = 0
    message: str = ''
    dest_path: Optional[Path] = None


@dataclass
class MigrationResult:
    ok: bool
    backup: Optional[BackupResult] = None
    types: list[TypeResult] = field(default_factory=list)
    message: str = ''

    @property
    def succeeded(self) -> int:
        return sum(1 for t in self.types if t.ok)

    @property
    def total(self) -> int:
        return len(self.types)


class MigrationEngine:
    """Migrate selected data types from an iOS backup to a destination."""

    def __init__(
        self,
        backup_root: str | Path,
        dest_root: str | Path,
        progress_cb: Optional[ProgressCB] = None,
    ):
        self.backup_root = Path(backup_root)
        self.dest_root = Path(dest_root)
        self.progress_cb = progress_cb

    # -- helpers -----------------------------------------------------------

    def _report(self, percent: int, stage: str, message: str) -> None:
        if self.progress_cb:
            self.progress_cb(percent, stage, message)

    def _resolve_db(self, data_type: DataType) -> Optional[Path]:
        """Resolve a DB-backed source file from its backup_domain path."""
        rel = DATA_TYPES[data_type].backup_domain
        if not rel:
            return None
        domain, _, path = rel.partition("/")
        entry = find_by_path(self.backup_root, path, domain=domain)
        if entry is None:
            # Fall back: try domain-less lookup.
            entry = find_by_path(self.backup_root, path)
        return resolve_blob(self.backup_root, entry) if entry else None

    # -- per-type handlers --------------------------------------------------

    def _migrate_contacts(self) -> TypeResult:
        db = self._resolve_db(DataType.CONTACTS)
        if db is None or not db.exists():
            return TypeResult(DataType.CONTACTS, False, 0, "AddressBook.sqlitedb not found in backup")
        out = self.dest_root / "apk_assets" / "contacts.vcf"
        n = write_vcards(db, out)
        ok = n > 0
        msg = "" if ok else "no contacts found in AddressBook"
        return TypeResult(DataType.CONTACTS, ok, n, msg, out)

    def _migrate_calendar(self) -> TypeResult:
        db = self._resolve_db(DataType.CALENDAR)
        if db is None or not db.exists():
            return TypeResult(DataType.CALENDAR, False, 0, "Calendar.sqlitedb not found in backup")
        out = self.dest_root / "apk_assets" / "calendar.ics"
        n = write_ics(db, out)
        ok = n > 0
        msg = "" if ok else "no events found in Calendar"
        return TypeResult(DataType.CALENDAR, ok, n, msg, out)

    def _migrate_photos(self) -> TypeResult:
        out = self.dest_root / "media" / "photos"
        n = extract_photos(self.backup_root, out, convert_heic=True)
        ok = n > 0
        msg = "" if ok else "no photos found under CameraRollDomain"
        return TypeResult(DataType.PHOTOS, ok, n, msg, out)

    def _migrate_videos(self) -> TypeResult:
        out = self.dest_root / "media" / "videos"
        # Photos and videos both live under CameraRollDomain; split by suffix.
        n = extract_videos(self.backup_root, out)
        ok = n > 0
        msg = "" if ok else "no videos found under CameraRollDomain"
        return TypeResult(DataType.VIDEOS, ok, n, msg, out)

    def _migrate_music(self) -> TypeResult:
        out = self.dest_root / "media" / "music"
        # Music files live under Media/iTunes_Control/Music in Manifest.
        n = self._copy_domain("Media/iTunes_Control/Music", out)
        ok = n > 0
        msg = "" if ok else "no music found under Media/iTunes_Control/Music"
        return TypeResult(DataType.MUSIC, ok, n, msg, out)

    def _migrate_notes(self) -> TypeResult:
        # iOS 17+ stores notes in AppDomainGroup-group.com.apple.notes/NoteStore.sqlite;
        # older iOS used HomeDomain/Library/Notes/notes.sqlite. Try both.
        db = None
        for domain, path in (
            ("AppDomainGroup-group.com.apple.notes", "NoteStore.sqlite"),
            ("HomeDomain", "Library/Notes/notes.sqlite"),
        ):
            entry = find_by_path(self.backup_root, path, domain=domain)
            if entry is None:
                entry = find_by_path(self.backup_root, path)
            if entry is not None:
                candidate = resolve_blob(self.backup_root, entry)
                if candidate.is_file():
                    db = candidate
                    break
        if db is None:
            return TypeResult(DataType.NOTES, False, 0, "NoteStore.sqlite not found in backup")
        assets_dir = self.dest_root / "apk_assets"
        # notes.txt is the legacy human-readable dump (still useful as a
        # portable archive / debug aid).
        txt_out = assets_dir / "notes.txt"
        n = write_notes(db, txt_out)
        # notes.json is the structured companion consumed by the HUAWEI
        # Notepad importer (core.write.notepad_import). One object per note
        # with title/body, so each note can be pushed into the Notepad app
        # via ACTION_SEND instead of being left as an opaque file in
        # /sdcard/Documents.
        json_out = assets_dir / "notes.json"
        n_json = write_notes_json(db, json_out)
        # Use the count from the JSON view (one record per note); both files
        # cover the same data, but JSON is the canonical input for the
        # importer.
        count = n_json if n_json else n
        ok = count > 0
        if not ok:
            msg = "no notes found in Notes store"
        elif not n_json:
            msg = "notes.txt written (json export failed)"
        else:
            msg = ""
        return TypeResult(DataType.NOTES, ok, count, msg, json_out)

    def _migrate_bookmarks(self) -> TypeResult:
        db = self._resolve_db(DataType.BOOKMARKS)
        if db is None or not db.exists():
            return TypeResult(DataType.BOOKMARKS, False, 0, "Bookmarks.db not found in backup")
        out = self.dest_root / "apk_assets" / "bookmarks.html"
        n = write_bookmarks(db, out)
        ok = n > 0
        msg = "" if ok else "no bookmarks found in Safari Bookmarks"
        return TypeResult(DataType.BOOKMARKS, ok, n, msg, out)

    def _resolve_reminders_dbs(self) -> list[Path]:
        """Resolve every Reminders CoreData sqlite file in the backup.

        Reminders live in multiple ``*.sqlite`` files under
        ``AppDomainGroup-group.com.apple.reminders/Container_v1/Stores``
        (one per account + a Data-local.sqlite). We collect them all.

        Note: the physical blob is named by SHA1 (no .sqlite suffix), so we
        filter by the manifest ``relative_path``, then resolve each blob.
        """
        domain = DATA_TYPES[DataType.REMINDERS].backup_domain
        prefix = domain.partition("/")[0]
        entries = find_by_domain(self.backup_root, prefix)
        dbs: list[Path] = []
        seen: set[str] = set()
        for e in entries:
            if not e.relative_path.endswith(".sqlite"):
                continue
            blob = resolve_blob(self.backup_root, e)
            if blob.is_file() and str(blob) not in seen:
                seen.add(str(blob))
                dbs.append(blob)
        return dbs

    def _migrate_reminders(self) -> TypeResult:
        dbs = self._resolve_reminders_dbs()
        if not dbs:
            return TypeResult(DataType.REMINDERS, False, 0, "no Reminders sqlite found in backup")
        out = self.dest_root / "apk_assets" / "reminders.ics"
        n = write_reminders(dbs, out)
        ok = n > 0
        msg = "" if ok else "no reminders found in Reminders store"
        return TypeResult(DataType.REMINDERS, ok, n, msg, out)

    def _copy_domain(self, domain: str, dest_dir: Path) -> int:
        from core.manifest import find_by_domain

        entries = find_by_domain(self.backup_root, domain)
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for i, e in enumerate(entries, start=1):
            src = resolve_blob(self.backup_root, e)
            if not src.is_file():
                continue
            suffix = Path(e.relative_path).suffix
            dst = dest_dir / f"{e.file_id}{suffix}"
            if not dst.exists():
                dst.write_bytes(src.read_bytes())
                copied += 1
        return copied

    # -- dispatch -----------------------------------------------------------

    def _handler(self, data_type: DataType):
        return {
            DataType.CONTACTS: self._migrate_contacts,
            DataType.CALENDAR: self._migrate_calendar,
            DataType.PHOTOS: self._migrate_photos,
            DataType.VIDEOS: self._migrate_videos,
            DataType.MUSIC: self._migrate_music,
            DataType.NOTES: self._migrate_notes,
            DataType.BOOKMARKS: self._migrate_bookmarks,
            DataType.REMINDERS: self._migrate_reminders,
        }[data_type]

    def run(self, data_types: Iterable[DataType]) -> MigrationResult:
        """Migrate the selected data types and return a summary."""
        types = list(data_types)
        result = MigrationResult(ok=True)
        total = len(types)

        for i, dt in enumerate(types, start=1):
            self._report(int((i - 1) / total * 100) if total else 100, "migrating", dt.value)
            try:
                tr = self._handler(dt)()
                result.types.append(tr)
            except Exception as exc:  # noqa: BLE001 - report per-type, keep going
                result.types.append(TypeResult(dt, False, 0, str(exc)))
            self._report(int(i / total * 100) if total else 100, "migrated", dt.value)

        if any(not t.ok for t in result.types):
            result.ok = False
        result.message = f"{result.succeeded}/{result.total} types migrated"
        return result


def backup_and_migrate(
    backup_dir: str | Path,
    dest_root: str | Path,
    data_types: Iterable[DataType],
    udid: Optional[str] = None,
    progress_cb: Optional[ProgressCB] = None,
) -> MigrationResult:
    """Convenience: run a fresh backup, then migrate. (Used by the GUI.)"""
    # Phase 1: backup
    backup_result = backup_full(
        backup_dir, udid=udid,
        progress_cb=lambda pct, msg: progress_cb(pct or 0, "backup", msg) if progress_cb else None,
    )
    if not backup_result.ok:
        return MigrationResult(ok=False, backup=backup_result, message=backup_result.message)

    # Phase 2: migrate — use the actual backup root that holds Manifest.db.
    engine = MigrationEngine(backup_result.backup_root, dest_root, progress_cb=progress_cb)
    result = engine.run(data_types)
    result.backup = backup_result
    return result
