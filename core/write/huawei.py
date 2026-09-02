"""HUAWEI-side orchestration — detect the phone and run the full import.

This is the "phase 3" of the transfer pipeline (after backup -> migrate):

  1. Detect the HUAWEI phone via ``adb devices``.
  2. Install the bundled PhoneMover Importer APK.
  3. Push converted files (contacts.vcf, calendar.ics, reminders.ics, …).
  4. Fire the import broadcast for each APK-backed data type.
  5. Report per-type results.

Media types (photos/videos/music) are delivered via adb push into the phone's
public media folders. Notes are imported into the HUAWEI Notepad app one by
one via ``ACTION_SEND`` (see core.write.notepad_import). Bookmarks still use
MTP / /sdcard/Documents because the HUAWEI Browser auto-detects them there.

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
    grant_permissions,
    import_calendar,
    import_contacts,
    import_reminders,
    install_apk,
    push_document_file,
    push_media_dir,
)
from core.write.notepad_import import (
    import_notes_to_notepad,
    load_notes_json,
)

# Which apk_assets filename maps to which adb import function.
_APK_ASSETS = {
    "contacts.vcf": ("contacts", import_contacts),
    "calendar.ics": ("calendar", import_calendar),
    "reminders.ics": ("reminders", import_reminders),
}

# Plain files delivered into /sdcard/Documents (no provider import exists).
# Only bookmarks remains: notes is imported into Notepad via ACTION_SEND
# (see core.write.notepad_import).
_DOCUMENT_ASSETS = {
    "bookmarks.html": "bookmarks",
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

    # 2b. Grant runtime permissions (contacts + calendar) via `pm grant`.
    # A broadcast receiver can't pop a permission dialog, so we grant them
    # over adb — the user already authorized USB debugging.
    try:
        failed_perms = grant_permissions(serial=serial)
        if failed_perms:
            log.warn(f"permissions not granted: {failed_perms}")
    except Exception as exc:  # noqa: BLE001 - best effort
        log.warn(f"permission grant failed: {exc}")

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

    # 5. Import notes into HUAWEI Notepad via ACTION_SEND (one note at a time).
    # Each note pops up the share dialog, we tap SAVE and the app creates a
    # new entry in the Notepad list. We do NOT push notes.txt into /sdcard/
    # Documents any more — that left the file sitting there with no path into
    # the Notepad app. The .txt file in apk_assets is kept as a portable
    # archive but is no longer delivered to the device.
    notes_json = assets / "notes.json"
    if notes_json.exists():
        report(95, "importing notes into Notepad")
        try:
            notes = load_notes_json(notes_json)
            total = len(notes)
            def _notes_progress(idx: int, total: int, msg: str) -> None:
                if total > 0:
                    pct = 95 + int(3 * (idx - 1) / total)
                    report(pct, f"note {idx}/{total}: {msg}")
            nres = import_notes_to_notepad(
                notes, serial=serial, progress_cb=_notes_progress
            )
            result.types.append({
                "type": "notes",
                "ok": nres.ok,
                "count": nres.imported,
                "message": nres.message,
            })
            log.info(f"notepad import: ok={nres.ok} imported={nres.imported} "
                     f"failed={nres.failed} total={nres.total}")
            if nres.errors:
                for err in nres.errors[:5]:
                    log.error(f"  notepad: {err}")
        except Exception as exc:  # noqa: BLE001
            result.types.append({"type": "notes", "ok": False, "count": 0,
                                 "message": f"notepad import failed: {exc}"})
            log.error("notepad import failed", exc)

    # 6. Push remaining plain documents (bookmarks.html) into Documents.
    # Bookmarks still rides MTP / /sdcard/Documents because the HUAWEI Browser
    # auto-detects bookmark.html there. Other document types (if added) can
    # be added to _DOCUMENT_ASSETS.
    for name, label in _DOCUMENT_ASSETS.items():
        local = assets / name
        if not local.exists():
            continue
        report(98, f"pushing {label}")
        try:
            dres = push_document_file(local, serial=serial)
            result.types.append(
                {"type": label, "ok": dres.ok, "count": dres.pushed, "message": dres.message}
            )
            log.info(f"push document {label}: ok={dres.ok} msg={dres.message}")
        except Exception as exc:  # noqa: BLE001
            result.types.append({"type": label, "ok": False, "count": 0, "message": str(exc)})
            log.error(f"push document {label} failed", exc)

    report(99, "import complete")
    if result.types and any(not t["ok"] for t in result.types):
        result.ok = False
    result.message = f"{result.succeeded}/{result.total} types imported"
    return result
