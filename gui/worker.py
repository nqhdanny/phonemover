"""Background worker — run migration off the UI thread."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.engine import MigrationEngine, MigrationResult
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
