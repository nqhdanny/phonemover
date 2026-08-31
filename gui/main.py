"""PhoneMover entry point — minimal PySide6 window (skeleton).

v1.0 UI language: English (default) / Russian.
Run:  python -m gui.main
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

APP_TITLE = "PhoneMover"


class MainWindow(QMainWindow):
    """Main application window (skeleton)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(960, 640)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        # Placeholder — real layout (device cards / data list / progress) comes next.
        label = QLabel("PhoneMover — iPhone to HUAWEI data transfer", central)
        layout.addWidget(label)
        self.setCentralWidget(central)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
