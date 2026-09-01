"""Vendor resource locator — locate bundled adb + APK inside the exe.

When PhoneMover is packaged as a onefile exe, adb.exe (and its DLLs) and the
importer APK are bundled inside via PyInstaller ``--add-binary``. At runtime
PyInstaller unpacks the Python side to ``sys._MEIPASS``, but ``--add-binary``
entries are also materialized there as plain files.

This module:
  1. Finds the bundled adb executable (unpacking to a temp dir if needed).
  2. Finds the bundled importer APK path.
  3. Falls back to a system ``adb`` on PATH for dev/unpackaged runs.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _resource_dir() -> Path:
    """Directory holding bundled resources (PyInstaller or source checkout)."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    # Running from source: resources live relative to this file's package.
    return Path(__file__).resolve().parent.parent.parent


def _bundled(name: str) -> Path | None:
    """Return the path of a bundled file, or None if not present."""
    candidates = [
        _resource_dir() / "vendor" / name,
        _resource_dir() / name,
        Path(sys._MEIPASS) / "vendor" / name if getattr(sys, "_MEIPASS", None) else None,
        Path(sys._MEIPASS) / name if getattr(sys, "_MEIPASS", None) else None,
    ]
    for c in candidates:
        if c and c.is_file():
            return c
    return None


_ADB_CANDIDATES = ("adb.exe", "adb")


def find_adb() -> str:
    """Locate the adb executable (bundled first, then PATH).

    On Windows the exe bundles adb.exe (+ DLLs); on other platforms (dev /
    CI) we prefer a system ``adb`` from PATH, since the bundled binary is
    Windows-only.
    """
    is_windows = sys.platform.startswith("win")

    # 1. Bundled adb inside the exe (Windows only — it's adb.exe).
    if is_windows:
        for name in _ADB_CANDIDATES:
            bundled = _bundled(name)
            if bundled:
                return str(bundled)

    # 2. System adb on PATH (dev / unpackaged / non-Windows).
    adb = shutil.which("adb")
    if adb:
        return adb

    raise RuntimeError(
        "adb not found — PhoneMover bundles adb on Windows, but it was not "
        "located. Install Android platform-tools."
    )


def find_apk() -> Path:
    """Locate the bundled importer APK. Raises if missing."""
    apk = _bundled("PhoneMoverImporter.apk")
    if apk:
        return apk
    # Dev fallback: look for a built APK under the repo.
    dev = _resource_dir() / "apk" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if dev.is_file():
        return dev
    raise FileNotFoundError(
        "Importer APK not found — build it with `gradle assembleDebug` "
        "or place PhoneMoverImporter.apk under vendor/."
    )


def ensure_adb_runtime() -> str:
    """Make sure the bundled adb (and its DLLs) are usable.

    PyInstaller onefile unpacks ``--add-binary`` files next to the exe's
    temp ``_MEIPASS`` dir; adb.exe and its DLLs land in the same folder, so
    adb runs directly from there. This is a no-op for bundled adb, but kept
    as an explicit hook for future relocation needs.
    """
    return find_adb()
