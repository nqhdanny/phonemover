"""Transfer wizard — step-by-step guided transfer dialog.

Replaces the single-window progress bar with an in-app wizard that walks the
user through the whole flow one step at a time:

  1. Connect iPhone
  2. Back up iPhone
  3. Connect HUAWEI phone
  4. Install helper + import data
  5. Done

Each step shows plain-language instructions (no console windows), a live
progress bar, and a scrolling log that is also written to ``phonemover.log``.

The wizard owns the ``BackupAndMigrateWorker``; progress signals drive the
step advancement. The main window passes in the same inputs it would have
used for the one-click flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.logging_util import log
from core.models import DataType
from i18n import t

from .worker import BackupAndMigrateWorker, DeviceScanWorker


class TransferWizard(QDialog):
    """Modal, guided transfer dialog."""

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

        self._worker: BackupAndMigrateWorker | None = None
        self._scan_worker: DeviceScanWorker | None = None
        self._current_step = 0
        self._result = None

        self._steps = [
            ("connect_iphone", "step.connect_iphone"),
            ("backup", "step.backup"),
            ("connect_huawei", "step.connect_huawei"),
            ("import", "step.import"),
            ("done", "step.done"),
        ]

        self.setWindowTitle(t("wizard.title"))
        self.resize(760, 520)
        self.setModal(True)
        self._build_ui()
        self._goto_step(0)
        # Start by scanning for the iPhone.
        self._start_iphone_scan()

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # Left: step list.
        self.step_list = QVBoxLayout()
        self.step_labels: list[QLabel] = []
        for _, key in self._steps:
            lbl = QLabel(t(key), self)
            lbl.setStyleSheet("color: #888; padding: 6px 10px;")
            self.step_labels.append(lbl)
            self.step_list.addWidget(lbl)
        self.step_list.addStretch(1)
        left = QWidget(self)
        left.setLayout(self.step_list)
        left.setFixedWidth(200)
        root.addWidget(left)

        # Right: instruction + progress + log + buttons.
        right = QVBoxLayout()
        right.setSpacing(10)

        self.instr_label = QLabel("", self)
        self.instr_label.setWordWrap(True)
        self.instr_label.setStyleSheet("font-size: 14px; color: #333;")
        self.instr_label.setMinimumHeight(48)
        right.addWidget(self.instr_label)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        right.addWidget(self.progress)

        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color: #666;")
        right.addWidget(self.status_label)

        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText(t("wizard.log_placeholder"))
        right.addWidget(self.log_edit, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton(t("action.cancel"), self)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)
        self.close_btn = QPushButton(t("wizard.close"), self)
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        right.addLayout(btn_row)

        right_widget = QWidget(self)
        right_widget.setLayout(right)
        root.addWidget(right_widget, stretch=1)

    def _goto_step(self, idx: int) -> None:
        self._current_step = idx
        for i, lbl in enumerate(self.step_labels):
            if i < idx:
                lbl.setStyleSheet("color: #2e7d32; padding: 6px 10px;")
            elif i == idx:
                lbl.setStyleSheet(
                    "color: #1565c0; font-weight: bold; padding: 6px 10px;"
                )
            else:
                lbl.setStyleSheet("color: #888; padding: 6px 10px;")

    def _append_log(self, line: str) -> None:
        self.log_edit.append(line)
        # Auto-scroll to bottom.
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    # -- Step 1: iPhone ----------------------------------------------------

    def _start_iphone_scan(self) -> None:
        self._goto_step(0)
        self.instr_label.setText(t("step.connect_iphone.instr"))
        self.status_label.setText(t("device.scanning"))
        self._append_log(t("step.connect_iphone.instr"))
        self._scan_worker = DeviceScanWorker(self)
        self._scan_worker.found.connect(self._on_iphone_found)
        self._scan_worker.empty.connect(self._on_iphone_empty)
        self._scan_worker.error.connect(self._on_iphone_error)
        self._scan_worker.start()

    def _on_iphone_found(self, devices) -> None:
        self.udid = devices[0].udid if devices and devices[0].udid else None
        self.status_label.setText(t("device.found"))
        self._append_log(t("device.found"))
        # Move to step 2: back up.
        self._start_backup()

    def _on_iphone_empty(self) -> None:
        self.status_label.setText(t("device.not_found"))
        self._append_log(t("device.not_found"))

    def _on_iphone_error(self, message: str) -> None:
        self.status_label.setText(t("device.not_found") + ": " + message)
        self._append_log("ERROR: " + message)

    # -- Step 2: backup ----------------------------------------------------

    def _start_backup(self) -> None:
        self._goto_step(1)
        self.instr_label.setText(t("step.backup.instr"))
        self._append_log(t("step.backup.instr"))
        self._run_worker()

    # -- Step 3-4: HUAWEI --------------------------------------------------

    def _run_worker(self) -> None:
        self._worker = BackupAndMigrateWorker(
            self.backup_dir, self.dest_root, self.data_types, udid=self.udid, parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, percent: int, stage: str, message: str) -> None:
        self.progress.setValue(percent)
        if stage == "backup":
            self._goto_step(1)
            self.status_label.setText(t("progress.backup"))
        elif stage == "migrate":
            self._goto_step(1)
            self.status_label.setText(t("progress.migrating"))
        elif stage == "huawei":
            self._goto_step(3)
            self.instr_label.setText(t("step.import.instr"))
            self.status_label.setText(t("progress.importing"))
        elif stage == "done":
            self._goto_step(4)
            self.status_label.setText(t("progress.done"))

        detail = message if message and message not in (
            "backing up", "migrating", "done", "importing to HUAWEI"
        ) else ""
        if detail:
            self._append_log(f"{percent}% {detail}")

    def _on_finished(self, result) -> None:
        self._result = result
        self._goto_step(4)
        self.progress.setValue(100)

        lines = []
        for tr in getattr(result, "types", []):
            mark = "OK " if tr.ok else "FAIL"
            detail = tr.message or (f"{tr.count} item(s)" if tr.ok else "no detail")
            lines.append(f"[{mark}] {tr.data_type.value}: {detail}")
        hw = getattr(result, "huawei", None)
        if hw is not None:
            if hw.apk_installed:
                lines.append("[OK] importer APK installed on HUAWEI")
            for ht in getattr(hw, "types", []):
                mark = "OK " if ht.get("ok") else "FAIL"
                lines.append(f"[{mark}] huawei/{ht.get('type')}: {ht.get('count', 0)} item(s)")

        for line in lines:
            self._append_log(line)
            log.info(line)

        if result.ok:
            self.instr_label.setText(t("step.done.instr_ok"))
            self.status_label.setText(t("progress.done"))
        else:
            self.instr_label.setText(t("step.done.instr_partial"))
            self.status_label.setText(
                t("result.summary", succeeded=result.succeeded, total=result.total)
            )
        log.info(f"=== transfer finished === ok={result.ok}")
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.status_label.setText(t("progress.failed") + ": " + message)
        self._append_log("ERROR: " + message)
        log.error(f"transfer failed: {message}")
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.requestInterruption()
            self._worker.terminate()
            self._worker = None
        if self._scan_worker:
            self._scan_worker.terminate()
            self._scan_worker = None
        log.info("transfer cancelled by user")
        self.reject()

    def closeEvent(self, evt) -> None:  # noqa: N802 - Qt API
        # Prevent closing mid-transfer unless it's finished/failed.
        if self._worker and self._worker.isRunning():
            evt.ignore()
            return
        super().closeEvent(evt)
