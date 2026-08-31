"""Photos/videos: extract media files from an iOS backup via Manifest.db.

Media lives under domain `Media/DCIM/<roll>/<file>` in the backup's
Manifest.db. Files are stored by SHA1 hash name in the backup root.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Callable, Optional

HEIC_SUFFIXES = {".heic", ".heif"}


def _manifest_conn(backup_root: str | Path) -> sqlite3.Connection:
    db = Path(backup_root) / "Manifest.db"
    if not db.exists():
        raise FileNotFoundError(f"Manifest.db not found in backup: {db}")
    return sqlite3.connect(str(db))


def list_media_files(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return [(file_id, relative_path)] for all files under Media/DCIM."""
    with _manifest_conn(backup_root) as conn:
        rows = conn.execute(
            """
            SELECT fileID, relativePath FROM Files
            WHERE domain LIKE 'Media/DCIM/%'
            """
        ).fetchall()
    return [(fid, rel) for fid, rel in rows]


def extract_photos(
    backup_root: str | Path,
    dest_dir: str | Path,
    convert_heic: bool = True,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> int:
    """Copy DCIM media into dest_dir (flat, numbered). Returns file count.

    HEIC files are converted to JPEG when convert_heic=True.
    """
    root = Path(backup_root)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    files = list_media_files(root)
    total = len(files)
    copied = 0

    for i, (file_id, rel) in enumerate(files, start=1):
        src = root / file_id
        if not src.is_file():
            continue
        suffix = Path(rel).suffix.lower()
        if convert_heic and suffix in HEIC_SUFFIXES:
            out_name = f"IMG_{i:05d}.jpg"
            _convert_heic(src, dest / out_name)
        else:
            out_name = Path(rel).name or f"MEDIA_{i:05d}{suffix}"
            shutil.copy2(src, dest / out_name)
        copied += 1
        if progress_cb and (i % 50 == 0 or i == total):
            progress_cb(int(i / total * 100) if total else 100, f"photos {i}/{total}")

    if progress_cb:
        progress_cb(100, f"done: {copied} files")
    return copied


def _convert_heic(src: Path, dst: Path) -> None:
    from pillow_heif import register_heif_opener
    from PIL import Image

    register_heif_opener()
    with Image.open(src) as img:
        img.convert("RGB").save(dst, "JPEG", quality=92)
