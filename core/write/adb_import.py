"""ADB import — push converted files to the HUAWEI device and trigger import.

The HUAWEI side runs the PhoneMover Importer APK (com.phonemover.importer),
which exposes a broadcast receiver that reads files from /sdcard/PhoneMover/
and inserts rows via the system ContentResolver.

Data-type -> channel mapping:

  contacts.vcf    -> APK inserts Contacts rows
  calendar.ics    -> APK inserts Calendar events
  reminders.ics   -> APK converts VTODO -> Calendar events
  bookmarks.html  -> MTP (HUAWEI browser imports the HTML file itself)
  notes.txt       -> MTP (dropped into Documents for the user)

This module wraps the `adb` commands the Windows host runs:
  1. adb install the APK (once)
  2. adb push contacts.vcf / calendar.ics / reminders.ics
  3. am broadcast ... to trigger import

The adb binary and APK are bundled inside the exe (see core.write.vendor).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from core.write.subprocess_util import run_cmd
from core.write.vendor import find_adb, find_apk

APK_PACKAGE = "com.phonemover.importer"
IMPORT_ACTION = "com.phonemover.importer.IMPORT"
DEVICE_DIR = "/sdcard/PhoneMover"


def _adb() -> str:
    return find_adb()


def _run(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return run_cmd(
        [_adb(), *args], capture_output=True, text=True, timeout=timeout
    )


@dataclass
class ImportResult:
    ok: bool
    count: int = 0
    message: str = ""


def install_apk(apk_path: str | Path | None = None) -> bool:
    """Install the importer APK onto the connected device.

    If ``apk_path`` is omitted, the bundled APK is used.
    """
    apk = Path(apk_path) if apk_path else find_apk()
    if not apk.exists():
        raise FileNotFoundError(f"APK not found: {apk}")
    proc = _run("install", "-r", str(apk))
    return "Success" in proc.stdout


def push_and_import(
    local_file: str | Path,
    data_type: str,  # "contacts" | "calendar" | "reminders"
    serial: Optional[str] = None,
) -> ImportResult:
    """Push a vCard/ICS file to the device and trigger import."""
    local = Path(local_file)
    if not local.exists():
        return ImportResult(False, 0, f"file not found: {local}")

    base = [_adb()]
    if serial:
        base += ["-s", serial]

    remote = f"{DEVICE_DIR}/{local.name}"

    # ensure device dir exists
    run_cmd(base + ["shell", "mkdir", "-p", DEVICE_DIR], capture_output=True)

    push = run_cmd(base + ["push", str(local), remote], capture_output=True, text=True)
    if push.returncode != 0:
        return ImportResult(False, 0, push.stderr.strip() or "adb push failed")

    broadcast = run_cmd(
        base
        + [
            "shell",
            "am",
            "broadcast",
            "-a",
            IMPORT_ACTION,
            "--es",
            "type",
            data_type,
            "--es",
            "path",
            remote,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    # `am broadcast` output looks like:
    #     Broadcasting: Intent { ... }
    #     Broadcast completed: result=-1, data="867"
    # (data= comes from BroadcastReceiver.setResultData(); -1 means RESULT_OK).
    out = (broadcast.stdout or "") + (broadcast.stderr or "")
    if broadcast.returncode != 0 and "result=" not in out:
        return ImportResult(False, 0, out.strip() or "am broadcast failed")

    # Parse the count. Prefer the value of data="<n>" (set via setResultData);
    # fall back to scanning for "data=<n>" without quotes.
    count = 0
    import re as _re
    m = _re.search(r'data="?(-?\d+)"?', out)
    if m:
        count = int(m.group(1))

    # Sanity check: result=-1 means RESULT_OK, anything else is a failure.
    result_m = _re.search(r"result=(-?\d+)", out)
    if result_m and int(result_m.group(1)) != -1 and count == 0:
        # Receiver returned RESULT_CANCELED (or threw) and we couldn't parse a
        # count — surface the raw output so the user sees what happened.
        return ImportResult(False, 0, out.strip())

    return ImportResult(True, count, out.strip())


def import_contacts(vcf_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(vcf_path, "contacts", serial)


def import_calendar(ics_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(ics_path, "calendar", serial)


def import_reminders(ics_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(ics_path, "reminders", serial)


# -- Media push ----------------------------------------------------------
#
# Photos/videos/music can't go through the importer APK (they're binary files,
# not provider rows). Instead we `adb push` them into the phone's public
# media folders so the HUAWEI Gallery / Music apps pick them up:
#
#   photos  -> /sdcard/DCIM/Camera/
#   videos  -> /sdcard/DCIM/Camera/   (Gallery shows both together)
#   music   -> /sdcard/Music/
#
# This replaces the earlier MTP removable-drive approach, which was fragile
# (drive letter detection) and never wired into the worker.

# Local dir name (under dest_root/media/<name>) -> remote device dir.
MEDIA_REMOTE_DIRS = {
    "photos": "/sdcard/DCIM/Camera",
    "videos": "/sdcard/DCIM/Camera",
    "music": "/sdcard/Music",
}


@dataclass
class MediaPushResult:
    ok: bool
    kind: str          # "photos" | "videos" | "music"
    pushed: int = 0
    failed: int = 0
    message: str = ""


def push_media_dir(
    local_dir: str | Path,
    kind: str,
    serial: Optional[str] = None,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> MediaPushResult:
    """Push every file in ``local_dir`` to the device's public media folder.

    ``kind`` selects the remote destination (photos/videos/music). Files are
    pushed one at a time so progress can be reported; any per-file failure is
    counted but does not abort the rest.
    """
    src = Path(local_dir)
    remote = MEDIA_REMOTE_DIRS.get(kind, "/sdcard/Download")

    base = [_adb()]
    if serial:
        base += ["-s", serial]

    if not src.is_dir():
        return MediaPushResult(True, kind, 0, 0, f"no {kind} to push (dir missing)")

    files = sorted(f for f in src.iterdir() if f.is_file())
    total = len(files)
    if total == 0:
        return MediaPushResult(True, kind, 0, 0, f"no {kind} files")

    # Ensure the remote dir exists.
    run_cmd(base + ["shell", "mkdir", "-p", remote], capture_output=True)

    pushed = 0
    failed = 0
    for i, f in enumerate(files, start=1):
        proc = run_cmd(
            base + ["push", str(f), f"{remote}/{f.name}"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode == 0:
            pushed += 1
        else:
            failed += 1
        if progress_cb:
            progress_cb(int(i / total * 100), f"{kind} {i}/{total}")

    ok = failed == 0
    msg = f"{kind}: {pushed} pushed" + (f", {failed} failed" if failed else "")
    return MediaPushResult(ok, kind, pushed, failed, msg)
