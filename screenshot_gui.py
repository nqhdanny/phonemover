import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from gui.main import MainWindow

app = QApplication(sys.argv)

win = MainWindow()
win.show()

# 先截英文
app.processEvents()
win.grab().save("/tmp/gui_en.png")

# 切到俄语再截
win.lang_combo.setCurrentIndex(1)
app.processEvents()
win.grab().save("/tmp/gui_ru.png")

print("saved /tmp/gui_en.png and /tmp/gui_ru.png")
