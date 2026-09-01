"""HUAWEI-side orchestration — detect the phone and run the full import.

This is the "phase 3" of the transfer pipeline (after backup -> migrate):

  1. Detect the HUAWEI phone via ``adb devices``.
  2. Install the bundled PhoneMover Importer APK.
  3. Push converted files (contacts.vcf, calendar.ics, reminders.ics, …).
  4. Fire the import broadcast for each APK-backed data type.
  5. Report per-type results.

Media types (photos/videos/music) and file types (bookmarks.html, notes.txt)
are delivered via MTP, which is handled separately (see core.write.mtp).

The adb binary and APK are bundled inside the exe (see core.write.vendor).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.write.subprocess_util import run_cmd
from core.write.vendor import find_adb, find_apk
from core.logging_util import log
from core.write.adb_import import (
    DEVICE_DIR,
    import_calendar,
    import_contacts,
    import_reminders,
    install_apk,
    push_media_dir,
)

# Which apk_assets filename maps to which adb import function.
_APK_ASSETS = {
    "contacts.vcf": ("contacts", import_contacts),
    "calendar.ics": ("calendar", import_calendar),
    "reminders.ics": ("reminders", import_reminders),
}

# Media dir name (under dest_root/media/<name>) -> adb push kind.
_MEDIA_KINDS = ("photos", "videos", "music")


@dataclass(frozen=True)
class AndroidDevice:
    serial: str
    state: str  # "device" | "unauthorized" | "offline"


@dataclass
class HuaweiResult:
    ok: bool
    apk_installed: bool = False
    types: list[dict] = field(default_factory=list)
    message: str = ""

    @property
    def succeeded(self) -> int:
        return sum(1 for t in self.types if t.get("ok"))

    @property
    def total(self) -> int:
        return len(self.types)


def list_android_devices() -> list[AndroidDevice]:
    """Enumerate connected Android/HUAWEI devices via adb.

    Returns an empty list when none are connected. Raises RuntimeError if adb
    itself cannot run.
    """
    adb = find_adb()
    proc = run_cmd(
        [adb, "devices"], capture_output=True, text=True, timeout=30
    )
    out = proc.stdout or ""
    devices: list[AndroidDevice] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append(AndroidDevice(serial=parts[0], state=parts[1]))
    return devices


def _pick_device(preferred: Optional[str]) -> Optional[AndroidDevice]:
    devices = list_android_devices()
    if not devices:
        return None
    if preferred:
        for d in devices:
            if d.serial == preferred:
                return d
    # Prefer the first "device" (authorized) entry.
    for d in devices:
        if d.state == "device":
            return d
    return devices[0]


def migrate_to_huawei(
    apk_assets_dir: str | Path,
    serial: Optional[str] = None,
    media_dir: Optional[str | Path] = None,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> HuaweiResult:
    """Install the importer APK and import all APK-backed assets + media.

    ``apk_assets_dir`` is the folder the engine writes to (``.../apk_assets``).
    For each recognized file (contacts.vcf / calendar.ics / reminders.ics) we
    push it to the device and fire the import broadcast.

    ``media_dir`` (optional) is the ``.../media`` folder the engine writes to
    (with ``photos/``, ``videos/``, ``music/`` subdirs). When provided, those
    files are pushed via adb into the phone's public media folders.
    """
    assets = Path(apk_assets_dir)
    result = HuaweiResult(ok=True)

    def report(pct: int, msg: str) -> None:
        if progress_cb:
            progress_cb(pct, msg)

    # 1. Detect device.
    report(5, "detecting HUAWEI device")
    device = _pick_device(serial)
    if device is None:
        log.warn("no Android device detected via adb")
        return HuaweiResult(False, message="no Android device detected via adb")
    if device.state != "device":
        state_hint = {
            "unauthorized": "device unauthorized — accept the USB debugging prompt on the phone",
            "offline": "device offline — replug the USB cable",
        }.get(device.state, device.state)
        log.warn(f"device not ready: {state_hint}")
        return HuaweiResult(False, message=f"device not ready: {state_hint}")
    serial = device.serial
    log.info(f"HUAWEI device detected: {serial}")

    # 2. Install APK.
    report(15, "installing importer APK")
    try:
        installed = install_apk(find_apk())
    except Exception as exc:  # noqa: BLE001
        log.error("APK install failed", exc)
        return HuaweiResult(False, message=f"APK install failed: {exc}")
    result.apk_installed = installed
    log.info(f"APK installed: {installed}")

    # 3. Push + import each APK-backed asset.
    total = sum(1 for name in _APK_ASSETS if (assets / name).exists())
    done = 0
    for name, (data_type, importer) in _APK_ASSETS.items():
        local = assets / name
        if not local.exists():
            continue
        report(20 + int(60 * done / max(total, 1)), f"importing {data_type}")
        try:
            res = importer(local, serial=serial)
            result.types.append(
                {"type": data_type, "ok": res.ok, "count": res.count, "message": res.message}
            )
            log.info(f"import {data_type}: ok={res.ok} count={res.count} msg={res.message}")
        except Exception as exc:  # noqa: BLE001
            result.types.append({"type": data_type, "ok": False, "count": 0, "message": str(exc)})
            log.error(f"import {data_type} failed", exc)
        done += 1

    # 4. Push media (photos/videos/music) via adb.
    if media_dir:
        mdir = Path(media_dir)
        media_kinds = [k for k in _MEDIA_KINDS if (mdir / k).is_dir()]
        m_total = len(media_kinds)
        for i, kind in enumerate(media_kinds):
            report(80 + int(15 * i / max(m_total, 1)), f"pushing {kind}")
            try:
                mres = push_media_dir(
                    mdir / kind,
                    kind,
                    serial=serial,
                    progress_cb=lambda pct, msg, _k=kind: report(
                        80 + int(15 * (i + pct / 100) / max(m_total, 1)), msg
                    ),
                )
                result.types.append(
                    {"type": kind, "ok": mres.ok, "count": mres.pushed, "message": mres.message}
                )
                log.info(f"push media {kind}: ok={mres.ok} pushed={mres.pushed} "
                         f"failed={mres.failed}")
            except Exception as exc:  # noqa: BLE001
                result.types.append({"type": kind, "ok": False, "count": 0, "message": str(exc)})
                log.error(f"push media {kind} failed", exc)

    report(95, "import complete")
    if result.types and any(not t["ok"] for t in result.types):
        result.ok = False
    result.message = f"{result.succeeded}/{result.total} types imported"
    return result
