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
from typing import Optional

from core.write.vendor import find_adb, find_apk

APK_PACKAGE = "com.phonemover.importer"
IMPORT_ACTION = "com.phonemover.importer.IMPORT"
DEVICE_DIR = "/sdcard/PhoneMover"


def _adb() -> str:
    return find_adb()


def _run(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
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
    subprocess.run(base + ["shell", "mkdir", "-p", DEVICE_DIR], capture_output=True)

    push = subprocess.run(base + ["push", str(local), remote], capture_output=True, text=True)
    if push.returncode != 0:
        return ImportResult(False, 0, push.stderr.strip() or "adb push failed")

    broadcast = subprocess.run(
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

    # `am broadcast` prints the result code and extras on success.
    out = (broadcast.stdout or "") + (broadcast.stderr or "")
    if broadcast.returncode != 0 and "result=" not in out:
        return ImportResult(False, 0, out.strip() or "am broadcast failed")

    # Parse the count from the broadcast extras (best-effort).
    count = 0
    for token in out.split():
        if token.startswith("data=") and token[5:].lstrip("-").isdigit():
            count = int(token[5:])
    return ImportResult(True, count, out.strip())


def import_contacts(vcf_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(vcf_path, "contacts", serial)


def import_calendar(ics_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(ics_path, "calendar", serial)


def import_reminders(ics_path: str | Path, serial: Optional[str] = None) -> ImportResult:
    return push_and_import(ics_path, "reminders", serial)
