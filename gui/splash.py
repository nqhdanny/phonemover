"""Splash screen — shown during heavy startup (PyInstaller unpack + first
device scan). Half-transparent overlay with the app logo, title, version,
and an animated spinner.

Lifecycle:
  splash = SplashScreen()
  splash.show()
  # ... run heavy work ...
  splash.finish(window)   # fades out and stops the spinner
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.__version__ import __version__
from i18n import t


class SpinnerWidget(QWidget):
    """A circular rotating spinner drawn with QPainter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(48, 48)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        # ~60 fps
        self._timer.setInterval(16)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        self._angle = (self._angle - 8) % 360  # rotate counter-clockwise
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 4
        rect = QRect(2, 2, side, side)
        # Faint background ring
        p.setPen(QPen(QColor(255, 255, 255, 30), 4))
        p.drawEllipse(rect)
        # Foreground arc, accent color, with a moving "head"
        p.setPen(QPen(QColor(86, 156, 214), 4, Qt.SolidLine, Qt.RoundCap))
        # Draw 8 short arcs around the circle; each is drawn with opacity
        # falling off so the spinner looks like a comet tail.
        step = 360 // 12
        for i in range(12):
            alpha = int(255 * (i + 1) / 12)
            p.setPen(QPen(QColor(86, 156, 214, alpha), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(
                rect.adjusted(2, 2, -2, -2),
                int((self._angle + i * step) * 16),
                int(step * 16 * 0.55),
            )
        p.end()


class SplashScreen(QWidget):
    """Frameless, translucent, top-most loading screen."""

    def __init__(self) -> None:
        # Tool | FramelessWindowHint | WindowStaysOnTopHint | WA_TranslucentBackground
        super().__init__(
            None,
            Qt.SplashScreen
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(420, 280)

        # Outer container (semi-transparent dark card)
        card = QFrame(self)
        card.setObjectName("splashCard")
        card.setStyleSheet(
            "#splashCard {"
            "  background-color: rgba(20, 24, 32, 220);"
            "  border: 1px solid rgba(255,255,255,30);"
            "  border-radius: 16px;"
            "}"
        )
        card.setFixedSize(420, 280)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        # Logo (reuse main app logo if present)
        from gui.main import LOGO_PATH

        logo_lbl = QLabel(card)
        pix = LOGO_PATH.parent and None  # type: ignore[unreachable]
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap(str(LOGO_PATH))
        scaled = pixmap.scaled(
            72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        logo_lbl.setPixmap(scaled)
        logo_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo_lbl, alignment=Qt.AlignCenter)

        # App name + version
        title = QLabel(t("app.version", version=__version__), card)
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #f5f7fa;")
        layout.addWidget(title)

        # Status message (updated by caller if needed)
        self.status_label = QLabel(t("device.scanning"), card)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #b9c0cc; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Spinner
        self.spinner = SpinnerWidget(card)
        spinner_row = QWidget(card)
        srow = QVBoxLayout(spinner_row)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.addWidget(self.spinner, alignment=Qt.AlignCenter)
        layout.addWidget(spinner_row)

        # Center on screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )

        self._fade: QPropertyAnimation | None = None

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def showEvent(self, evt) -> None:  # noqa: N802 - Qt API
        super().showEvent(evt)
        self.spinner.start()

    def hideEvent(self, evt) -> None:  # noqa: N802 - Qt API
        self.spinner.stop()
        super().hideEvent(evt)

    def fade_out(self, duration_ms: int = 220, on_finished=None) -> None:
        """Animate window opacity from 1.0 to 0.0, then hide."""
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(duration_ms)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.OutQuad)
        if on_finished:
            self._fade.finished.connect(on_finished)
        self._fade.start()

    def finish(self, target_window) -> None:
        """Fade out, then hide and raise the target window."""
        def _done() -> None:
            self.hide()
            target_window.show()
            target_window.raise_()
            target_window.activateWindow()
        self.fade_out(on_finished=_done)