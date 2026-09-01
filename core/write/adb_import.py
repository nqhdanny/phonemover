"""ADB import — push converted files to the HUAWEI device and trigger import.

The HUAWEI side runs the PhoneMover Importer APK (com.phonemover.importer),
which exposes a foreground Activity + receiver that reads files from /data/local/tmp/PhoneMover/
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
  3. am start ... to trigger import (foreground Activity)

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
DEVICE_DIR = "/data/local/tmp/PhoneMover"


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
    ok = "Success" in proc.stdout
    if ok:
        # Launch the invisible Activity once so the app leaves the "stopped"
        # state. A stopped app never receives broadcasts and is blocked by
        # EMUI's background-execution policy.
        _run(
            "shell", "am", "start",
            "-n", f"{APK_PACKAGE}/.ImportActivity",
            timeout=30,
        )
    return ok


# Runtime (dangerous) permissions the importer APK needs. On Android 6+ these
# must be granted at runtime; a broadcast receiver cannot pop a permission
# dialog, so we grant them via `adb shell pm grant` (the user has already
# authorized USB debugging, so this is equivalent to tapping "Allow").
REQUIRED_PERMISSIONS = [
    "android.permission.READ_CONTACTS",
    "android.permission.WRITE_CONTACTS",
    "android.permission.READ_CALENDAR",
    "android.permission.WRITE_CALENDAR",
    "android.permission.POST_NOTIFICATIONS",
]


def grant_permissions(serial: Optional[str] = None) -> list[str]:
    """Grant the APK's runtime permissions via `adb shell pm grant`.

    Returns a list of permission names that failed to grant (empty = all ok).
    Some HUAWEI builds reject `pm grant` for certain permissions; those are
    reported so the caller can surface a hint.
    """
    base = [_adb()]
    if serial:
        base += ["-s", serial]
    failed: list[str] = []
    for perm in REQUIRED_PERMISSIONS:
        proc = run_cmd(
            base + ["shell", "pm", "grant", APK_PACKAGE, perm],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # Success prints nothing; errors print something like
        # "Operation not allowed" / "Unknown permission".
        if proc.returncode != 0 or "not allowed" in out.lower() or "unknown" in out.lower():
            failed.append(perm)
    return failed


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

    # Android 12+ / EMUI blocks manifest receivers from receiving background
    # broadcasts ("Background execution not allowed"), so we trigger the import
    # through the foreground ImportActivity instead of `am broadcast`. The
    # Activity has Theme.NoDisplay and finishes immediately.
    start = run_cmd(
        base
        + [
            "shell", "am", "start",
            "-n", f"{APK_PACKAGE}/.ImportActivity",
            "--es", "type", data_type,
            "--es", "path", remote,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    out = (start.stdout or "") + (start.stderr or "")

    # The Activity writes the count to the app-private files dir (scoped
    # storage prevents writing to /sdcard/PhoneMover on Android 11+). Read it
    # back via `adb shell run-as <pkg> cat files/result_<type>.txt`.
    count = 0
    raw_count = ""
    for _attempt in range(8):  # retry: the Activity import may take a moment
        cat = run_cmd(
            base + ["shell", "run-as", APK_PACKAGE, "cat", f"files/result_{data_type}.txt"],
            capture_output=True, text=True, timeout=30,
        )
        raw_count = (cat.stdout or "").strip()
        if raw_count:
            break
        import time as _time
        _time.sleep(0.5)
    if raw_count:
        try:
            count = int(raw_count)
        except ValueError:
            count = 0

    # Success is determined by the count >= 0 (the APK writes -1 on error).
    if count < 0:
        return ImportResult(False, 0, out.strip() or f"import {data_type} failed")

    return ImportResult(True, count, out.strip())


def import_contacts(vcf_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(vcf_path, "contacts", serial)


def import_calendar(ics_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(ics_path, "calendar", serial)


def import_reminders(ics_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(ics_path, "reminders", serial)


# -- Document push -------------------------------------------------------
#
# notes.txt and bookmarks.html are plain files the HUAWEI device cannot import
# through a provider (there is no public API for the HUAWEI Notepad / Browser to
# auto-import them). We `adb push` them into /sdcard/Documents so the user can
# open them directly; the HUAWEI Files app lists them under "Documents".

DOCUMENT_REMOTE_DIR = "/sdcard/Documents"


@dataclass
class DocumentPushResult:
    ok: bool
    name: str          # base filename (e.g. "notes.txt")
    pushed: int = 0
    message: str = ""


def push_document_file(
    local_file: str | Path,
    serial: Optional[str] = None,
) -> DocumentPushResult:
    """Push a single text/html file into the device's Documents folder.

    Returns a result describing whether the file was delivered. The file is not
    auto-imported into any app (HUAWEI Notepad has no import API); it is made
    available to the user under /sdcard/Documents.
    """
    local = Path(local_file)
    if not local.exists():
        return DocumentPushResult(False, local.name, 0, f"file not found: {local}")

    base = [_adb()]
    if serial:
        base += ["-s", serial]

    run_cmd(base + ["shell", "mkdir", "-p", DOCUMENT_REMOTE_DIR], capture_output=True)
    proc = run_cmd(
        base + ["push", str(local), f"{DOCUMENT_REMOTE_DIR}/{local.name}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    ok = proc.returncode == 0
    msg = f"{local.name}: pushed" if ok else (proc.stderr.strip() or f"push failed")
    return DocumentPushResult(ok, local.name, 1 if ok else 0, msg)


# -- Media push ----------------------------------------------------------
#
# Photos/videos/music can't go through the importer APK (they're binary files,
# not provider rows). Instead we `adb push` them into the phone's public
# media folders so the HUAWEI Gallery / Music apps pick them up:
#
#   photos/<album>/*  -> /sdcard/DCIM/<album>/*     (albums preserved)
#   videos/Video/*    -> /sdcard/DCIM/Video/*       (separate video folder)
#   music/*           -> /sdcard/Music/*
#
# This replaces the earlier MTP removable-drive approach, which was fragile
# (drive letter detection) and never wired into the worker.
#
# The extractor (core.parse.photos) already writes photos grouped by album
# (Camera, WhatsApp, Imported, ...) and videos into a single "Video" subfolder.
# Here we map each local subfolder onto the device's DCIM/<album> directory so
# the HUAWEI Gallery shows each album as its own album.

# Remote root directory per media kind. Photos/videos use DCIM and keep their
# local subfolder (album) name as the remote subfolder; music is flat.
MEDIA_REMOTE_ROOTS = {
    "photos": "/sdcard/DCIM",
    "videos": "/sdcard/DCIM",
    "music": "/sdcard/Music",
}

# Backward-compatible alias (kept for any external importer).
MEDIA_REMOTE_DIRS = {
    "photos": "/sdcard/DCIM/Camera",
    "videos": "/sdcard/DCIM/Video",
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
    """Push media under ``local_dir`` to the device, preserving album subfolders.

    For ``photos`` and ``videos``, each subfolder of ``local_dir`` is an album
    (e.g. ``Camera``, ``WhatsApp``, ``Video``) and is pushed to
    ``/sdcard/DCIM/<subfolder>/`` so the HUAWEI Gallery shows each album
    separately. ``music`` is pushed flat into ``/sdcard/Music/``.

    Files are pushed one at a time so progress can be reported; any per-file
    failure is counted but does not abort the rest.
    """
    src = Path(local_dir)
    root_remote = MEDIA_REMOTE_ROOTS.get(kind, "/sdcard/Download")

    base = [_adb()]
    if serial:
        base += ["-s", serial]

    if not src.is_dir():
        return MediaPushResult(True, kind, 0, 0, f"no {kind} to push (dir missing)")

    # Flatten the local tree into (relative_subdir, file) pairs.
    items: list[tuple[str, Path]] = []
    if kind in ("photos", "videos"):
        # Album-aware: walk subfolders, each subfolder = an album.
        for sub in sorted(src.iterdir()):
            if sub.is_dir():
                for f in sorted(sub.iterdir()):
                    if f.is_file():
                        items.append((sub.name, f))
            elif sub.is_file():
                # A stray file at the top level goes into the kind root.
                items.append(("", sub))
    else:
        # Music: flat.
        for f in sorted(src.iterdir()):
            if f.is_file():
                items.append(("", f))

    total = len(items)
    if total == 0:
        return MediaPushResult(True, kind, 0, 0, f"no {kind} files")

    pushed = 0
    failed = 0
    scanned_dirs: set[str] = set()
    for i, (sub, f) in enumerate(items, start=1):
        remote = f"{root_remote}/{sub}" if sub else root_remote
        if remote not in scanned_dirs:
            run_cmd(base + ["shell", "mkdir", "-p", remote], capture_output=True)
            scanned_dirs.add(remote)
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

    # Trigger a media scan over the root so the HUAWEI Gallery / Music apps
    # index every newly pushed album. adb push writes files directly and does
    # NOT update the MediaStore database; without this the files are on disk
    # but invisible in the gallery. The importer APK exposes a "scan" action
    # that runs MediaScannerConnection.scanFile() over the whole directory.
    _trigger_media_scan(base, root_remote)

    ok = failed == 0
    msg = f"{kind}: {pushed} pushed" + (f", {failed} failed" if failed else "")
    return MediaPushResult(ok, kind, pushed, failed, msg)


def _trigger_media_scan(base: list[str], remote_dir: str) -> None:
    """Ask the importer APK to index the pushed media directory.

    Uses the APK's ``scan`` action, which calls
    ``MediaScannerConnection.scanFile()`` on every file under ``remote_dir``.
    This is far more reliable than the ``MEDIA_SCANNER_SCAN_FILE`` broadcast,
    which modern Android/HUAWEI ignore for directory paths.
    """
    run_cmd(
        base
        + [
            "shell", "am", "start",
            "-n", f"{APK_PACKAGE}/.ImportActivity",
            "--es", "type", "scan",
            "--es", "path", remote_dir,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
