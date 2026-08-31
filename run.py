"""PhoneMover launcher — PyInstaller entry point.

Packaged as a windowed (no-console) Windows exe:
    pyinstaller --onefile --windowed --name PhoneMover run.py
"""

import sys

from gui.main import main

if __name__ == "__main__":
    sys.exit(main())
