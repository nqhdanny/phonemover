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
from core.manifest import find_by_path, resolve_blob
from core.models import DATA_TYPES, DataType
from core.parse.calendar import write_ics
from core.parse.contacts import write_vcards
from core.parse.photos import extract_photos, extract_videos
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
