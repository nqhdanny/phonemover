"""Manifest traversal — unified lookup of files inside an iOS backup.

An iTunes/pymobiledevice3 backup stores a Manifest.db (SQLite) with a
table mapping every file to its SHA1-named blob in the backup root:

  Files(fileID, domain, relativePath, flags, file)

Real iOS backups store blobs in a **sharded layout**: files are grouped
into 256 subdirectories named by the first two hex chars of their fileID
(e.g. `31/31bb7ba8...`). Older/synthetic backups may keep blobs flat in
the backup root. `resolve_blob` handles both layouts.

This module is the single source of truth for locating data by domain/path,
so individual parsers don't hardcode backup layout details.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ManifestEntry:
    file_id: str
    domain: str
    relative_path: str

    @property
    def blob_path(self) -> str:
        """Path of the actual file blob, relative to the backup root."""
        return self.file_id


def open_manifest(backup_root: str | Path) -> sqlite3.Connection:
    db = Path(backup_root) / "Manifest.db"
    if not db.exists():
        raise FileNotFoundError(f"Manifest.db not found in backup: {db}")
    return sqlite3.connect(str(db))


def list_files(backup_root: str | Path) -> list[ManifestEntry]:
    """Return every file entry in the backup manifest."""
    with open_manifest(backup_root) as conn:
        rows = conn.execute(
            "SELECT fileID, domain, relativePath FROM Files"
        ).fetchall()
    return [ManifestEntry(fid, domain or "", rel or "") for fid, domain, rel in rows]


def find_by_domain(
    backup_root: str | Path, domain_prefix: str
) -> list[ManifestEntry]:
    """Return entries whose domain equals domain_prefix or lives under it."""
    prefix = domain_prefix.rstrip("/")
    with open_manifest(backup_root) as conn:
        rows = conn.execute(
            "SELECT fileID, domain, relativePath FROM Files WHERE domain = ? OR domain LIKE ?",
            (prefix, prefix + "/%"),
        ).fetchall()
    return [ManifestEntry(fid, domain or "", rel or "") for fid, domain, rel in rows]


def find_by_path(
    backup_root: str | Path, relative_path: str, domain: Optional[str] = None
) -> Optional[ManifestEntry]:
    """Return the entry for an exact relativePath (optionally within a domain)."""
    with open_manifest(backup_root) as conn:
        if domain:
            row = conn.execute(
                "SELECT fileID, domain, relativePath FROM Files WHERE relativePath = ? AND domain = ?",
                (relative_path, domain),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT fileID, domain, relativePath FROM Files WHERE relativePath = ?",
                (relative_path,),
            ).fetchone()
    if not row:
        return None
    return ManifestEntry(row[0], row[1] or "", row[2] or "")


def resolve_blob(backup_root: str | Path, entry: ManifestEntry) -> Path:
    """Absolute path to the file blob for a manifest entry.

    iOS backups shard blobs into 256 subdirs by the first two hex chars of
    the fileID (e.g. `31/31bb7ba8...`). We try that layout first, then fall
    back to a flat layout (`<root>/<fileID>`) for older/synthetic backups.
    """
    root = Path(backup_root)
    fid = entry.file_id

    # Sharded layout: first two hex chars as a subdirectory.
    if len(fid) >= 2:
        sharded = root / fid[:2] / fid
        if sharded.is_file():
            return sharded

    # Flat layout: file directly under the backup root.
    flat = root / fid
    if flat.is_file():
        return flat

    # Neither exists — return the sharded path so callers can report a
    # precise missing-file location (`.exists()` will be False).
    return root / fid[:2] / fid if len(fid) >= 2 else flat


def blob_path(backup_root: str | Path, file_id: str) -> Path:
    """Resolve a fileID to its physical blob path (sharded-then-flat)."""
    entry = ManifestEntry(file_id, "", "")
    return resolve_blob(backup_root, entry)
