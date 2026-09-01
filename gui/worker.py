"""Background worker — run migration / device scan off the UI thread."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.backup import backup_full
from core.engine import MigrationEngine
from core.models import DataType


class MigrationWorker(QThread):
    """Run MigrationEngine.run() in a thread; emit progress + finished."""

    progress = Signal(int, str)      # (percent, message)
    finished_ok = Signal(object)     # MigrationResult
    failed = Signal(str)             # error message

    def __init__(
        self,
        backup_root: str,
        dest_root: str,
        data_types: list[DataType],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.backup_root = backup_root
        self.dest_root = dest_root
        self.data_types = data_types

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            engine = MigrationEngine(
                self.backup_root,
                self.dest_root,
                progress_cb=self._on_progress,
            )
            result = engine.run(self.data_types)
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.failed.emit(str(exc))

    def _on_progress(self, percent: int, stage: str, message: str) -> None:
        self.progress.emit(percent, message or stage)


class BackupAndMigrateWorker(QThread):
    """One-click flow: full backup, then migrate — with phased progress."""

    # stage: "backup" | "migrate" | "done"
    progress = Signal(int, str, str)   # (percent 0-100, stage, message)
    finished_ok = Signal(object)       # MigrationResult
    failed = Signal(str)               # error message

    def __init__(
        self,
        backup_dir: str,
        dest_root: str,
        data_types: list[DataType],
        udid: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.backup_dir = backup_dir
        self.dest_root = dest_root
        self.data_types = data_types
        self.udid = udid

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            # Phase 1: backup
            self.progress.emit(0, "backup", "backing up")
            backup = backup_full(
                self.backup_dir,
                udid=self.udid,
                progress_cb=lambda pct, msg: self.progress.emit(
                    pct or 0, "backup", msg or "backing up"
                ),
            )
            if not backup.ok:
                self.failed.emit(backup.message)
                return

            # Phase 2: migrate
            self.progress.emit(0, "migrate", "migrating")
            engine = MigrationEngine(
                backup.backup_root,
                self.dest_root,
                progress_cb=lambda pct, stage, msg: self.progress.emit(
                    pct, "migrate", msg or stage
                ),
            )
            result = engine.run(self.data_types)
            result.backup = backup

            # Phase 3: import to HUAWEI (APK-backed types + media via adb).
            # If a HUAWEI phone is connected via adb, install the APK, push
            # contacts/calendar/reminders + photos/videos/music.
            apk_assets = Path(self.dest_root) / "apk_assets"
            media_dir = Path(self.dest_root) / "media"
            huawei = None
            if apk_assets.exists() or media_dir.exists():
                try:
                    from core.write.huawei import HuaweiResult, migrate_to_huawei

                    self.progress.emit(80, "huawei", "importing to HUAWEI")
                    huawei = migrate_to_huawei(
                        apk_assets,
                        media_dir=media_dir,
                        progress_cb=lambda pct, msg: self.progress.emit(
                            pct, "huawei", msg
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - huawei import is best-effort
                    huawei = HuaweiResult(ok=False, message=str(exc))
            result.huawei = huawei

            self.progress.emit(100, "done", "done")
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.failed.emit(str(exc))


class DeviceScanWorker(QThread):
    """Enumerate connected iPhones off the UI thread."""

    found = Signal(object)      # list[IDevice]
    empty = Signal()            # no devices
    error = Signal(str)         # environmental error (driver/usbmuxd)

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            from core.device import DeviceError, list_iphones

            devices = list_iphones()
            if devices:
                self.found.emit(devices)
            else:
                self.empty.emit()
        except DeviceError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
