"""Album mapping — resolve the photo -> album relationship from Photos.sqlite.

iOS 17+ backups store the camera roll and user albums in a CoreData database
``Media/PhotoData/Photos.sqlite`` under the ``CameraRollDomain``. The tables we
need are:

  ZGENERICALBUM  — albums (ZTITLE, ZKIND, ZUUID)
  ZASSET         — photos (ZFILENAME, ZDIRECTORY, ZUUID, ZKINDSUBTYPE)
  Z_33ASSETS     — many-to-many link (Z_33ALBUMS -> ZGENERICALBUM.Z_PK,
                   Z_3ASSETS -> ZASSET.Z_PK)

The physical photo blobs live under two locations in the backup (relative to
the ``Media/`` prefix stored in ZASSET.ZDIRECTORY):

  DCIM/100APPLE/…                 — camera-roll originals (IMG_xxxx)
  PhotoData/CPLAssets/groupNNN/…  — originals imported from apps (WhatsApp etc.)

Everything else under ``Media/PhotoData/`` (Thumbnails, Metadata, MISC, …) is
derived/sidecar data and must NOT be treated as a user photo. This module is
the single source of truth for the album mapping and the photo-file list.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.manifest import find_by_path, resolve_blob

# CoreData ZKIND value for a *real user album* (e.g. "WhatsApp", created when
# the user imports photos from an app). Other kinds (1510, 1600+, folders,
# memories) are derived/smart albums with no user title and are skipped.
USER_ALBUM_KIND = 2

# The ZDIRECTORY value (relative to Media/) that marks a camera-roll original.
CAMERA_ROLL_DIR = "DCIM/100APPLE"

# Suffixes used to tell photos from videos. HEIC is converted to JPEG later.
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".heic", ".heif"}
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".avi", ".3gp", ".mpg", ".mpeg"}


@dataclass(frozen=True)
class PhotoAsset:
    """A single original photo/video and its album assignment."""

    file_id: str          # SHA1 fileID of the blob in the backup
    filename: str         # original filename (e.g. IMG_0004.HEIC)
    album: str            # destination album name (Camera or a user album)
    is_video: bool        # True for videos (suffix in VIDEO_SUFFIXES)
    date_taken: int = 0   # Unix timestamp (seconds) of the capture time, 0 if unknown


def _photos_sqlite_path(backup_root: str | Path) -> Optional[Path]:
    """Resolve the Photos.sqlite blob inside the backup, if present."""
    entry = find_by_path(backup_root, "Media/PhotoData/Photos.sqlite", domain="CameraRollDomain")
    if entry is None:
        # Some backups flatten the domain; try without it.
        entry = find_by_path(backup_root, "Media/PhotoData/Photos.sqlite")
    if entry is None:
        return None
    blob = resolve_blob(backup_root, entry)
    return blob if blob.is_file() else None


def _load_albums(conn: sqlite3.Connection) -> dict[int, str]:
    """Return {album_Z_PK: album_title} for titled user albums."""
    albums: dict[int, str] = {}
    try:
        rows = conn.execute(
            "SELECT Z_PK, ZTITLE, ZKIND FROM ZGENERICALBUM "
            "WHERE ZTITLE IS NOT NULL AND ZTITLE != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return albums  # older/synthetic backups may lack the table
    for pk, title, kind in rows:
        if kind == USER_ALBUM_KIND:
            albums[pk] = title
    return albums


def _load_album_membership(conn: sqlite3.Connection) -> dict[int, list[int]]:
    """Return {asset_Z_PK: [album_Z_PK, ...]} from the join table."""
    members: dict[int, list[int]] = {}
    try:
        rows = conn.execute("SELECT Z_33ALBUMS, Z_3ASSETS FROM Z_33ASSETS").fetchall()
    except sqlite3.OperationalError:
        return members
    for album_pk, asset_pk in rows:
        members.setdefault(asset_pk, []).append(album_pk)
    return members


def _load_assets(conn: sqlite3.Connection) -> list[tuple[int, str, str, int]]:
    """Return [(asset_Z_PK, ZDIRECTORY, ZFILENAME, date_taken_unix)] for every asset.

    The capture time is read from ``ZASSET.ZDATECREATED`` (a CoreData timestamp
    measured in seconds since 2001-01-01). It is converted to a Unix timestamp
    (seconds since 1970-01-01) so the writer can stamp it into the JPEG EXIF —
    the HUAWEI Gallery sorts its "Photos" timeline by EXIF DateTimeOriginal, and
    without it converted photos are indexed with an empty ``date_taken`` and are
    invisible in the timeline view.

    Older/synthetic backups may lack the ``ZDATECREATED`` column; in that case
    the capture time is simply 0 (unknown).
    """
    try:
        rows = conn.execute(
            "SELECT Z_PK, ZDIRECTORY, ZFILENAME, ZDATECREATED FROM ZASSET "
            "WHERE ZFILENAME IS NOT NULL AND ZFILENAME != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        # Fall back to the pre-date_taken schema (no ZDATECREATED column).
        try:
            rows = conn.execute(
                "SELECT Z_PK, ZDIRECTORY, ZFILENAME, NULL FROM ZASSET "
                "WHERE ZFILENAME IS NOT NULL AND ZFILENAME != ''"
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    out: list[tuple[int, str, str, int]] = []
    for pk, directory, filename, date_created in rows:
        out.append((pk, directory, filename, _coredata_to_unix(date_created)))
    return out


# Seconds between the CoreData reference date (2001-01-01) and the Unix epoch
# (1970-01-01). Apple's CoreData timestamps use the 2001 epoch.
COREDATA_EPOCH_OFFSET = 978307200


def _coredata_to_unix(value) -> int:
    """Convert a CoreData timestamp (seconds since 2001-01-01) to Unix seconds.

    Returns 0 when ``value`` is None, non-numeric, or out of a sane range
    (e.g. pre-2000 or far future), so callers can treat 0 as "unknown".
    """
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return 0
    if not (0 < secs < 4_000_000_000):  # ~year 2096 upper bound
        return 0
    unix = int(secs) + COREDATA_EPOCH_OFFSET
    return unix if unix > 0 else 0


def build_album_map(backup_root: str | Path) -> dict[str, list[PhotoAsset]]:
    """Return {album_name: [PhotoAsset, ...]} for all original photos.

    Camera-roll originals (ZDIRECTORY == ``DCIM/100APPLE``) are assigned to
    the ``Camera`` album. Photos belonging to a titled user album (via the
    Z_33ASSETS join) are assigned to that album. An original that belongs to
    no titled album and is not the camera roll is assigned to ``Imported``.

    Note: only *still images* are mapped here. Videos (including Live Photo
    .MOV sidecars, which are not rows in ZASSET) are collected separately by
    :func:`list_video_files`.

    If Photos.sqlite is absent (older backup), returns an empty mapping.
    """
    root = Path(backup_root)
    db_path = _photos_sqlite_path(root)
    if db_path is None:
        # Fallback: older iOS backups have no Photos.sqlite, so recover the
        # camera-roll originals straight from the manifest directories.
        return _fallback_photo_map(root)

    conn = sqlite3.connect(str(db_path))
    try:
        albums = _load_albums(conn)
        members = _load_album_membership(conn)
        assets = _load_assets(conn)
    finally:
        conn.close()

    result: dict[str, list[PhotoAsset]] = {}
    for asset_pk, directory, filename, date_taken in assets:
        # Only real originals live under DCIM/100APPLE or PhotoData/CPLAssets.
        directory = directory or ""
        if not (directory == CAMERA_ROLL_DIR or directory.startswith("PhotoData/CPLAssets/")):
            continue

        suffix = Path(filename).suffix.lower()
        if suffix not in PHOTO_SUFFIXES:
            continue  # videos are handled separately

        # Album assignment: titled user album first, then camera roll.
        album: Optional[str] = None
        for album_pk in members.get(asset_pk, []):
            title = albums.get(album_pk)
            if title:
                album = title
                break

        if album is None:
            album = "Camera" if directory == CAMERA_ROLL_DIR else "Imported"

        result.setdefault(album, []).append(
            PhotoAsset(
                file_id=_asset_file_id(root, directory, filename),
                filename=filename,
                album=album,
                is_video=False,
                date_taken=date_taken,
            )
        )

    return result


def list_video_files(backup_root: str | Path) -> list[PhotoAsset]:
    """Return all original video files (including Live Photo .MOV sidecars).

    Videos are not reliably present in ZASSET (Live Photo sidecars are stored
    only as the paired .HEIC in ZASSET), so we scan the manifest for original
    video blobs under the two original directories:
      - Media/DCIM/100APPLE/*.MOV (Live Photo sidecars)
      - Media/PhotoData/CPLAssets/**/*.MOV|*.MP4 (app-imported videos)

    They are all assigned to the ``Video`` album (see the writer, which maps
    that album to the device's video directory).
    """
    from core.manifest import find_by_domain

    root = Path(backup_root)
    result: list[PhotoAsset] = []
    seen: set[str] = set()
    for entry in find_by_domain(root, "CameraRollDomain"):
        rel = entry.relative_path
        suffix = Path(rel).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            continue
        # Only original directories, not thumbnails/derivatives.
        if not (
            rel.startswith("Media/DCIM/100APPLE/")
            or rel.startswith("Media/PhotoData/CPLAssets/")
            or rel.startswith("100APPLE/")
        ):
            continue
        if entry.file_id in seen:
            continue
        seen.add(entry.file_id)
        result.append(
            PhotoAsset(
                file_id=entry.file_id,
                filename=Path(rel).name,
                album="Video",
                is_video=True,
            )
        )
    return result


def _fallback_photo_map(backup_root: Path) -> dict[str, list[PhotoAsset]]:
    """Recover photos from the manifest when Photos.sqlite is absent.

    Older iOS backups (pre-17) store camera-roll originals under
    ``Media/DCIM/100APPLE/`` or the legacy ``100APPLE/`` prefix, with no
    album database. All such still images are assigned to the ``Camera``
    album; there is no album structure to preserve.
    """
    from core.manifest import find_by_domain

    result: dict[str, list[PhotoAsset]] = {}
    seen: set[str] = set()
    for entry in find_by_domain(backup_root, "CameraRollDomain"):
        rel = entry.relative_path
        suffix = Path(rel).suffix.lower()
        if suffix not in PHOTO_SUFFIXES:
            continue
        # Accept both the modern "Media/DCIM/100APPLE/..." and legacy
        # "100APPLE/..." prefixes, but skip thumbnails/derivatives.
        if not (rel.startswith("Media/DCIM/100APPLE/") or rel.startswith("100APPLE/")):
            continue
        if entry.file_id in seen:
            continue
        seen.add(entry.file_id)
        result.setdefault("Camera", []).append(
            PhotoAsset(
                file_id=entry.file_id,
                filename=Path(rel).name,
                album="Camera",
                is_video=False,
            )
        )
    return result


def _asset_file_id(backup_root: Path, directory: str, filename: str) -> str:
    """Resolve an asset (directory + filename) to its Manifest fileID.

    The asset's ZDIRECTORY is relative to ``Media/``, so the manifest
    relativePath is ``Media/<directory>/<filename>``.
    """
    rel = "Media/{}/{}".format(directory, filename)
    entry = find_by_path(backup_root, rel, domain="CameraRollDomain")
    if entry is None:
        entry = find_by_path(backup_root, rel)
    return entry.file_id if entry else ""


def list_original_assets(backup_root: str | Path) -> list[PhotoAsset]:
    """Flat list of all original photos and videos (flattened album map)."""
    out: list[PhotoAsset] = []
    for assets in build_album_map(backup_root).values():
        out.extend(assets)
    out.extend(list_video_files(backup_root))
    return out
