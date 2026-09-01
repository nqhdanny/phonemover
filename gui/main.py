"""PhoneMover GUI — MobileTrans-style transfer window (EN/RU).

Layout (960×640):
  - header: title + language selector
  - left: device status + data type checkboxes
  - right: destination folder picker
  - bottom: progress bar + start/cancel + log

Run:  python -m gui.main
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.__version__ import __version__
from core.models import DATA_TYPES, DataType, v1_data_types
from i18n import LANGUAGES, set_language, t

from .splash import SplashScreen
from .worker import BackupAndMigrateWorker, DeviceScanWorker

# Data type -> i18n key
_TYPE_KEY = {
    DataType.CONTACTS: 'data.contacts',
    DataType.PHOTOS: 'data.photos',
    DataType.VIDEOS: 'data.videos',
    DataType.MUSIC: 'data.music',
    DataType.CALENDAR: 'data.calendar',
}


def _logo_path() -> Path:
    """Locate assets/logo.png - works in dev and inside a PyInstaller exe."""
    base = getattr(sys, '_MEIPASS', None)
    candidates = [
        Path(base) / 'assets' / 'logo.png' if base else None,
        Path(__file__).resolve().parent.parent / 'assets' / 'logo.png',
    ]
    for p in candidates:
        if p and p.is_file():
            return p
    return candidates[1]


LOGO_PATH = _logo_path()


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, initial_devices: list | None = None) -> None:
        super().__init__()
        self._worker: BackupAndMigrateWorker | None = None
        self._scan_worker: DeviceScanWorker | None = None
        self._udid: str | None = None
        self._type_checks: dict[DataType, QCheckBox] = {}
        self._build_ui()
        self.setWindowTitle(t('app.title'))
        # OS-level window icon: taskbar, title bar, Alt-Tab.
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        # If the splash thread already scanned devices, render that state
        # immediately rather than showing "Scanning..." forever.
        if initial_devices:
            # Pre-scanned during splash — render the result directly.
            self._on_scan_found(initial_devices)
            self.refresh_btn.setEnabled(True)
        else:
            self._kick_scan()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addLayout(self._build_body(), stretch=1)
        root.addLayout(self._build_footer())
        self.setCentralWidget(central)

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        # Logo (left of title)
        logo_label = QLabel(self)
        pixmap = QPixmap(str(LOGO_PATH))
        scaled = pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label.setPixmap(scaled)
        logo_label.setFixedWidth(56)
        layout.addWidget(logo_label)

        # Title column: PhoneMover vX.Y.Z + subtitle
        title_col = QVBoxLayout()
        title = QLabel(t('app.version', version=__version__), self)
        title.setStyleSheet('font-size: 22px; font-weight: bold;')
        subtitle = QLabel(t('app.subtitle'), self)
        subtitle.setStyleSheet('color: #666;')
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, stretch=1)

        self.lang_combo = QComboBox(self)
        for lang in LANGUAGES:
            self.lang_combo.addItem(t('lang.' + lang), lang)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        layout.addWidget(self.lang_combo)
        return layout

    def _build_body(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(self._build_device_panel(), stretch=1)
        layout.addWidget(self._build_dest_panel(), stretch=1)
        return layout

    def _build_device_panel(self) -> QGroupBox:
        box = QGroupBox(t('data.title'), self)
        self.data_group = box
        v = QVBoxLayout(box)

        self.device_label = QLabel(t('device.scanning'), box)
        self.device_label.setStyleSheet('color: #888;')
        v.addWidget(self.device_label)

        self.refresh_btn = QPushButton(t('device.refresh'), box)
        self.refresh_btn.clicked.connect(self._on_refresh)
        v.addWidget(self.refresh_btn)

        # data type checkboxes (v1.0 types)
        for dt in v1_data_types():
            cb = QCheckBox(t(_TYPE_KEY[dt]), box)
            cb.setChecked(True)
            self._type_checks[dt] = cb
            v.addWidget(cb)

        v.addStretch(1)
        return box

    def _build_dest_panel(self) -> QGroupBox:
        box = QGroupBox(t('dest.title'), self)
        self.dest_group = box
        v = QVBoxLayout(box)

        self.dest_folder_label = QLabel(t('dest.folder'), box)
        v.addWidget(self.dest_folder_label)
        self.dest_hint_label = QLabel(t('dest.hint'), box)
        self.dest_hint_label.setStyleSheet('color: #888; font-size: 11px;')
        self.dest_hint_label.setWordWrap(True)
        v.addWidget(self.dest_hint_label)
        row = QHBoxLayout()
        self.dest_edit = QLineEdit(box)
        self.dest_edit.setPlaceholderText(r'D:\PhoneMover\out')
        row.addWidget(self.dest_edit, stretch=1)
        self.browse_btn = QPushButton(t('dest.browse'), box)
        self.browse_btn.clicked.connect(self._on_browse)
        row.addWidget(self.browse_btn)
        v.addLayout(row)

        v.addStretch(1)
        return box

    def _build_footer(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel(t('progress.waiting'), self)
        layout.addWidget(self.status_label)

        # log area: per-type success/failure detail
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(120)
        self.log_edit.setPlaceholderText("""transferred.""")
        layout.addWidget(self.log_edit)

        row = QHBoxLayout()
        self.start_btn = QPushButton(t('action.start'), self)
        self.start_btn.clicked.connect(self._on_start)
        row.addWidget(self.start_btn)
        self.cancel_btn = QPushButton(t('action.cancel'), self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)
        return layout

    # -- language ----------------------------------------------------------

    def _retranslate(self) -> None:
        self.setWindowTitle(t('app.title'))
        self.device_label.setText(t('device.scanning'))
        self.refresh_btn.setText(t('device.refresh'))
        self.browse_btn.setText(t('dest.browse'))
        self.start_btn.setText(t('action.start'))
        self.cancel_btn.setText(t('action.cancel'))
        self.status_label.setText(t('progress.waiting'))
        for dt, cb in self._type_checks.items():
            cb.setText(t(_TYPE_KEY[dt]))
        self.dest_folder_label.setText(t('dest.folder'))
        self.dest_hint_label.setText(t('dest.hint'))
        # group box titles
        self.data_group.setTitle(t('data.title'))
        self.dest_group.setTitle(t('dest.title'))

    def _on_lang_changed(self, index: int) -> None:
        lang = self.lang_combo.itemData(index)
        set_language(lang)
        self._retranslate()

    # -- slots -------------------------------------------------------------

    def _kick_scan(self) -> None:
        # Start the background device scanner. Used by _on_refresh and on
        # first launch when no pre-scanned devices were supplied.
        self.device_label.setText(t('device.scanning'))
        self.refresh_btn.setEnabled(False)
        self._scan_worker = DeviceScanWorker(self)
        self._scan_worker.found.connect(self._on_scan_found)
        self._scan_worker.empty.connect(self._on_scan_empty)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_refresh(self) -> None:
        self._kick_scan()

    def _on_scan_found(self, devices) -> None:
        self._udid = devices[0].udid if devices and devices[0].udid else None
        udids = ', '.join(d.udid for d in devices if d.udid)
        self.device_label.setText(t('device.found') + (f' ({udids})' if udids else ''))
        self.device_label.setStyleSheet('color: #2e7d32;')

    def _on_scan_empty(self) -> None:
        self.device_label.setText(t('device.not_found'))
        self.device_label.setStyleSheet('color: #c62828;')

    def _on_scan_error(self, message: str) -> None:
        self.device_label.setText(t('device.not_found') + ': ' + message)
        self.device_label.setStyleSheet('color: #c62828;')

    def _on_scan_done(self) -> None:
        self.refresh_btn.setEnabled(True)
        self._scan_worker = None

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t('dest.folder'))
        if path:
            self.dest_edit.setText(path)

    def _selected_types(self) -> list[DataType]:
        return [dt for dt, cb in self._type_checks.items() if cb.isChecked()]

    def _on_start(self) -> None:
        selected = self._selected_types()
        if not selected:
            QMessageBox.warning(self, t('app.title'), t('data.title'))
            return
        backup_dir = self.dest_edit.text().strip()
        if not backup_dir:
            QMessageBox.warning(self, t('app.title'), t('dest.folder'))
            return

        # One-click flow: back up iPhone into backup_dir, then migrate into
        # <backup_dir>/PhoneMover_out (predictable sibling folder, avoids
        # the Windows Path('D:/foo').parent == 'D:' pitfall).
        dest_root = str(Path(backup_dir) / 'PhoneMover_out')

        self._worker = BackupAndMigrateWorker(
            backup_dir, dest_root, selected, udid=self._udid, parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status_label.setText(t('progress.backup'))
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.requestInterruption()
            self._worker.terminate()
            self._worker = None
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(t('progress.waiting'))

    def _on_progress(self, percent: int, stage: str, message: str) -> None:
        self.progress.setValue(percent)
        if stage == 'backup':
            label = t('progress.backup')
        elif stage == 'migrate':
            label = t('progress.migrating')
        else:
            label = t('progress.done')
        # show percent + short detail
        detail = message if message and message not in ('backing up', 'migrating', 'done') else ''
        self.status_label.setText(f'{label} {percent}%' + (f' — {detail}' if detail else ''))

    def _on_finished(self, result) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(100)

        # write per-type detail to the log
        lines = []
        for tr in getattr(result, "types", []):
            mark = 'OK ' if tr.ok else 'FAIL'
            detail = tr.message or (f'{tr.count} item(s)' if tr.ok else 'no detail')
            lines.append(f"[{mark}] {tr.data_type.value}: {detail}")
        if hasattr(result, 'backup') and result.backup and getattr(result.backup, 'backup_root', None):
            lines.append(f"backup: {result.backup.backup_root}")
        self.log_edit.setPlainText("\n".join(lines))

        if result.ok:
            self.status_label.setText(t('progress.done'))
        else:
            self.status_label.setText(
                t('result.summary', succeeded=result.succeeded, total=result.total)
            )
        self._worker = None

    def _on_failed(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(t('progress.failed') + ': ' + message)
        self._worker = None


def main() -> int:
    """Show a splash, warm up heavy imports/scan on a background thread,
    then fade the splash out and reveal the main window."""
    import time

    app = QApplication(sys.argv)

    splash = SplashScreen()
    splash.show()
    app.processEvents()

    from PySide6.QtCore import QThread, QTimer, Signal

    MIN_SPLASH_MS = 1500  # never flash past the user unnoticed

    class _WarmupWorker(QThread):
        ready = Signal(object)  # list[IDevice]

        def run(self) -> None:  # noqa: D102
            try:
                from core.device import list_iphones
                devices = list_iphones()
            except Exception as exc:  # noqa: BLE001
                devices = []
                print(f"warmup: device scan failed: {exc}")
            self.ready.emit(devices)

    warmup_start = time.monotonic()
    warmup = _WarmupWorker()
    devices_holder: list = []

    def _reveal(devs) -> None:
        elapsed_ms = int((time.monotonic() - warmup_start) * 1000)
        remaining = max(0, MIN_SPLASH_MS - elapsed_ms)
        if remaining > 0:
            QTimer.singleShot(remaining, lambda: _do_reveal(devs))
        else:
            _do_reveal(devs)

    def _do_reveal(devs) -> None:
        splash.set_status("Loading interface...")
        window = MainWindow(devs)
        window.resize(960, 640)
        splash.finish(window)

    warmup.ready.connect(_reveal)
    warmup.start()

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
