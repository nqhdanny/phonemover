"""Backup engine — full iPhone backup via pymobiledevice3's Python API.

Uses Mobilebackup2Service directly (no subprocess) so it works identically
when packaged into a PyInstaller exe — there is no `python` interpreter
available inside a frozen app.

The backup is written into `<dest_dir>/<udid>/` (see Mobilebackup2Service
docstring). This module returns the *actual* backup root that holds
Manifest.db, not the parent we passed in.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

ProgressCB = Callable[[int, str], None]  # (percent 0-100, stage message)

_MANIFEST = "Manifest.db"


@dataclass
class BackupResult:
    ok: bool
    dest_dir: Path       # the dir we passed in (parent)
    backup_root: Path    # the actual dir containing Manifest.db (<dest>/<udid>)
    udid: str = ""
    encrypted: bool = False
    message: str = ""


def _find_backup_root(dest: Path) -> Optional[Path]:
    """Locate the directory holding Manifest.db under dest (shallow scan)."""
    if (dest / _MANIFEST).exists():
        return dest
    if dest.exists():
        for child in dest.iterdir():
            if child.is_dir() and (child / _MANIFEST).exists():
                return child
    return None


async def _backup_async(
    dest: Path,
    udid: Optional[str],
    password: Optional[str],
    progress_cb: Optional[ProgressCB],
) -> BackupResult:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

    result = BackupResult(ok=False, dest_dir=dest, backup_root=dest, udid=udid or "")

    lockdown = await create_using_usbmux(serial=udid, autopair=True)
    try:
        async with Mobilebackup2Service(lockdown) as backup_client:
            # Resolve the actual udid if not provided.
            if not udid:
                udid = getattr(backup_client, "_udid", None) or ""
                result.udid = udid

            last_pct = -1

            def _on_progress(pct: float) -> None:
                nonlocal last_pct
                p = int(round(pct))
                if p != last_pct and progress_cb:
                    progress_cb(p, f"backing up {p}%")
                last_pct = p

            await backup_client.backup(
                full=True,
                backup_directory=str(dest),
                progress_callback=_on_progress,
                password=password or "",
            )

            if progress_cb:
                progress_cb(100, "backup complete")
    finally:
        await lockdown.close()

    actual_root = _find_backup_root(dest)
    if actual_root is not None:
        result.backup_root = actual_root
        if actual_root != dest:
            result.udid = actual_root.name

    result.ok = actual_root is not None
    result.encrypted = bool(password)
    result.message = (
        f"Backup completed at {actual_root}" if actual_root else "Backup failed: no Manifest.db produced"
    )
    return result


def backup_full(
    dest_dir: str | Path,
    udid: Optional[str] = None,
    password: Optional[str] = None,
    progress_cb: Optional[ProgressCB] = None,
    python_bin: str | None = None,  # kept for API compatibility (ignored)
) -> BackupResult:
    """Create a full iPhone backup into dest_dir (writes into <dest>/<udid>).

    - udid: optional, back up a specific device when several are connected.
    - password: passphrase for encrypted backups (if the user enabled it).
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        return asyncio.run(_backup_async(dest, udid, password, progress_cb))
    except Exception as exc:  # noqa: BLE001 - surface to UI
        return BackupResult(
            ok=False,
            dest_dir=dest,
            backup_root=dest,
            udid=udid or "",
            message=f"Backup failed: {exc}",
        )


def estimate_backup_size(dest_dir: str | Path) -> int:
    """Total bytes already in a backup directory (for UI display)."""
    dest = Path(dest_dir)
    if not dest.exists():
        return 0
    return sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())


def available_disk_space(dest_dir: str | Path) -> int:
    return shutil.disk_usage(str(dest_dir)).free
