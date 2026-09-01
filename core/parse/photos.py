"""Photos/videos: extract media files from an iOS backup.

Real iOS 17+ backups store camera media under domain `CameraRollDomain`
(NOT the legacy `Media/DCIM` assumed by earlier versions). Files are stored
by SHA1 hash name in the backup root, with their real name/extension in
`relativePath` (e.g. `100APPLE/IMG_0001.JPG`, `100APPLE/IMG_0002.MOV`).

Photos and videos both live under CameraRollDomain, so we split them by
file extension at extraction time.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from core.manifest import find_by_domain, blob_path

# The domain where the camera roll lives in a real backup.
CAMERA_ROLL_DOMAIN = "CameraRollDomain"

HEIC_SUFFIXES = {".heic", ".heif"}
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".heic", ".heif"}
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".avi", ".3gp", ".mpg", ".mpeg"}


def list_media_files(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return [(file_id, relative_path)] for all files under CameraRollDomain."""
    return [(e.file_id, e.relative_path) for e in find_by_domain(backup_root, CAMERA_ROLL_DOMAIN)]


def _filter_by_suffix(files: list[tuple[str, str]], suffixes: set[str]) -> list[tuple[str, str]]:
    """Keep only entries whose relativePath suffix is in `suffixes`."""
    out = []
    for file_id, rel in files:
        suffix = Path(rel).suffix.lower()
        if suffix in suffixes:
            out.append((file_id, rel))
    return out


def list_photos(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return photo entries only (image suffixes)."""
    return _filter_by_suffix(list_media_files(backup_root), PHOTO_SUFFIXES)


def list_videos(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return video entries only (video suffixes)."""
    return _filter_by_suffix(list_media_files(backup_root), VIDEO_SUFFIXES)


def extract_photos(
    backup_root: str | Path,
    dest_dir: str | Path,
    convert_heic: bool = True,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> int:
    """Copy CameraRoll photos into dest_dir (flat, numbered). Returns count.

    HEIC files are converted to JPEG when convert_heic=True.
    """
    root = Path(backup_root)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    files = list_photos(root)
    total = len(files)
    copied = 0

    for i, (file_id, rel) in enumerate(files, start=1):
        src = blob_path(root, file_id)
        if not src.is_file():
            continue
        suffix = Path(rel).suffix.lower()
        if convert_heic and suffix in HEIC_SUFFIXES:
            out_name = f"IMG_{i:05d}.jpg"
            try:
                _convert_heic(src, dest / out_name)
            except Exception:  # noqa: BLE001 - corrupted/unsupported HEIC: fall back to raw copy
                shutil.copy2(src, dest / Path(rel).name)
        else:
            out_name = Path(rel).name or f"MEDIA_{i:05d}{suffix}"
            shutil.copy2(src, dest / out_name)
        copied += 1
        if progress_cb and (i % 50 == 0 or i == total):
            progress_cb(int(i / total * 100) if total else 100, f"photos {i}/{total}")

    if progress_cb:
        progress_cb(100, f"done: {copied} files")
    return copied


def extract_videos(
    backup_root: str | Path,
    dest_dir: str | Path,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> int:
    """Copy CameraRoll videos into dest_dir (flat, numbered). Returns count."""
    root = Path(backup_root)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    files = list_videos(root)
    total = len(files)
    copied = 0

    for i, (file_id, rel) in enumerate(files, start=1):
        src = blob_path(root, file_id)
        if not src.is_file():
            continue
        suffix = Path(rel).suffix.lower()
        out_name = Path(rel).name or f"VIDEO_{i:05d}{suffix}"
        shutil.copy2(src, dest / out_name)
        copied += 1
        if progress_cb and (i % 50 == 0 or i == total):
            progress_cb(int(i / total * 100) if total else 100, f"videos {i}/{total}")

    if progress_cb:
        progress_cb(100, f"done: {copied} files")
    return copied


def _convert_heic(src: Path, dst: Path) -> None:
    from pillow_heif import register_heif_opener
    from PIL import Image

    register_heif_opener()
    with Image.open(src) as img:
        img.convert("RGB").save(dst, "JPEG", quality=92)
