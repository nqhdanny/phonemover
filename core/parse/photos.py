"""Photos/videos: extract media files from an iOS backup, preserving albums.

Real iOS 17+ backups store the camera roll and user albums in
``Media/PhotoData/Photos.sqlite`` (see :mod:`core.parse.albums`). This module
uses that mapping so photos are grouped by album and videos are separated
from still images, instead of flattening everything into a single folder.

The destination layout is:

  <dest_dir>/<album>/<filename>     for photos (Camera, WhatsApp, Imported, …)
  <dest_dir>/Video/<filename>       for videos (incl. Live Photo .MOV sidecars)

where ``<dest_dir>`` is the caller-supplied output root (e.g.
``dest_root/media/photos`` for photos and ``dest_root/media/videos`` for
videos). The HUAWEI side then maps those subfolders onto the device.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from core.manifest import blob_path
from core.parse.albums import build_album_map, list_video_files

# Re-export suffix sets for callers that import them from here.
from core.parse.albums import PHOTO_SUFFIXES, VIDEO_SUFFIXES  # noqa: F401

HEIC_SUFFIXES = {".heic", ".heif"}

# The album name that videos are assigned to.
VIDEO_ALBUM = "Video"


def list_media_files(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return [(file_id, relative_path)] for all original photos + videos.

    This replaces the old "every file under CameraRollDomain" behaviour, which
    incorrectly included thumbnails and metadata. It is derived from the album
    map + video list so it only contains real originals.
    """
    from core.parse.albums import list_original_assets

    return [(a.file_id, a.filename) for a in list_original_assets(backup_root) if a.file_id]


def list_photos(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return photo entries only (image suffixes), from the album map."""
    from core.parse.albums import list_original_assets

    return [
        (a.file_id, a.filename)
        for a in list_original_assets(backup_root)
        if a.file_id and not a.is_video
    ]


def list_videos(backup_root: str | Path) -> list[tuple[str, str]]:
    """Return video entries only (video suffixes), from the video list."""
    return [(a.file_id, a.filename) for a in list_video_files(backup_root) if a.file_id]


def extract_photos(
    backup_root: str | Path,
    dest_dir: str | Path,
    convert_heic: bool = True,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> int:
    """Copy photos into ``dest_dir`` grouped by album. Returns count.

    Photos are written to ``dest_dir/<album>/<filename>``. HEIC files are
    converted to JPEG when ``convert_heic=True``.
    """
    root = Path(backup_root)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    album_map = build_album_map(root)
    total = sum(len(v) for v in album_map.values())
    copied = 0
    i = 0

    for album, assets in album_map.items():
        album_dir = dest / album
        album_dir.mkdir(parents=True, exist_ok=True)
        for asset in assets:
            i += 1
            src = blob_path(root, asset.file_id)
            if not src.is_file():
                continue
            suffix = Path(asset.filename).suffix.lower()
            if convert_heic and suffix in HEIC_SUFFIXES:
                out_name = Path(asset.filename).with_suffix(".jpg").name
                try:
                    _convert_heic(src, album_dir / out_name)
                except Exception:  # noqa: BLE001 - fall back to raw copy
                    shutil.copy2(src, album_dir / asset.filename)
            else:
                shutil.copy2(src, album_dir / asset.filename)
            copied += 1
            if progress_cb and (i % 50 == 0 or i == total):
                progress_cb(int(i / total * 100) if total else 100, "photos {}/{}".format(i, total))

    if progress_cb:
        progress_cb(100, "done: {} files".format(copied))
    return copied


def extract_videos(
    backup_root: str | Path,
    dest_dir: str | Path,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> int:
    """Copy videos into ``dest_dir`` (single ``Video`` subfolder). Returns count.

    Videos are written to ``dest_dir/Video/<filename>`` so the HUAWEI side can
    map that folder to the device's video directory (separate from photos).
    """
    root = Path(backup_root)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    videos = list_video_files(root)
    total = len(videos)
    copied = 0
    video_dir = dest / VIDEO_ALBUM
    video_dir.mkdir(parents=True, exist_ok=True)

    for i, asset in enumerate(videos, start=1):
        src = blob_path(root, asset.file_id)
        if not src.is_file():
            continue
        shutil.copy2(src, video_dir / asset.filename)
        copied += 1
        if progress_cb and (i % 50 == 0 or i == total):
            progress_cb(int(i / total * 100) if total else 100, "videos {}/{}".format(i, total))

    if progress_cb:
        progress_cb(100, "done: {} files".format(copied))
    return copied


def _convert_heic(src: Path, dst: Path) -> None:
    from pillow_heif import register_heif_opener
    from PIL import Image

    register_heif_opener()
    with Image.open(src) as img:
        img.convert("RGB").save(dst, "JPEG", quality=92)
