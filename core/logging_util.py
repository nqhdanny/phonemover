"""File logging for PhoneMover.

Writes a ``phonemover.log`` next to the destination/backup folder (or, failing
that, the user's home directory) so users can inspect exactly what happened
without a console window. Every line is timestamped.

The logger is process-wide (a module-level ``Logger`` singleton) so the GUI
and the core modules can log from anywhere without threading it through every
call signature. Use it like:

    from core.logging_util import log
    log.info("backup started")
    log.error("adb push failed", exc)
"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

_LOG_LOCK = threading.Lock()


class Logger:
    """A minimal thread-safe file logger with a settable destination."""

    def __init__(self) -> None:
        self._path: Optional[Path] = None
        self._fallback: Optional[Path] = None

    def setup(self, base_dir: str | Path | None = None) -> Path:
        """Choose the log file location and return its path.

        Preference order:
          1. ``<base_dir>/phonemover.log`` (the destination/backup folder)
          2. ``~/phonemover.log`` (home directory fallback)
        """
        if base_dir:
            p = Path(base_dir) / "phonemover.log"
        else:
            p = Path.home() / "phonemover.log"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Touch the file to confirm it is writable.
            with open(p, "a", encoding="utf-8"):
                pass
            self._path = p
        except OSError:
            p = Path.home() / "phonemover.log"
            self._path = p
        self._fallback = self._path
        return self._path

    @property
    def path(self) -> Optional[Path]:
        return self._path or self._fallback

    def _write(self, level: str, msg: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} [{level}] {msg}"
        # Always mirror to stderr so dev runs and frozen-app debugging keep
        # working even before a destination is chosen.
        print(line, file=sys.stderr, flush=True)
        target = self.path
        if target is None:
            return
        with _LOG_LOCK:
            try:
                with open(target, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def info(self, msg: str) -> None:
        self._write("INFO", msg)

    def warn(self, msg: str) -> None:
        self._write("WARN", msg)

    def error(self, msg: str, exc: BaseException | None = None) -> None:
        if exc is not None:
            msg += "\n" + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        self._write("ERROR", msg)


log = Logger()
