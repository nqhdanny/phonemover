"""Cross-platform subprocess helpers for PhoneMover.

All subprocess calls in the codebase should go through these helpers so that:

  1. On Windows, console windows never flash open (the "black box" the user
     reported). We pass ``CREATE_NO_WINDOW`` so adb / pymobiledevice3 / etc.
     run silently in the background.
  2. stdout/stderr are captured and, when requested, written to the log file.

The two entry points mirror stdlib subprocess:

  run_cmd(args, ...)      -> CompletedProcess   (blocking, captures output)
  popen_cmd(args, ...)    -> Popen              (streaming, for progress)

Both accept the same extra kwargs as subprocess.run / subprocess.Popen and
add the platform-specific creationflags automatically.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Sequence

# On Windows, stop the console window from appearing. On POSIX this flag does
# not exist, so we only set it when running on Windows.
if sys.platform.startswith("win"):
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
else:
    _NO_WINDOW = 0


def _flags(extra: int = 0) -> int:
    """Return the creationflags value for a subprocess call."""
    return _NO_WINDOW | extra


def run_cmd(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run() that never flashes a console window on Windows.

    Passes through all stdlib kwargs (capture_output, text, timeout, input,
    check, env, cwd, shell, ...). creationflags is set automatically; if the
    caller passes its own creationflags it is OR-ed with CREATE_NO_WINDOW.
    """
    if "creationflags" in kwargs:
        kwargs["creationflags"] = _flags(kwargs["creationflags"])
    else:
        kwargs["creationflags"] = _flags()
    return subprocess.run(list(args), **kwargs)


def popen_cmd(args: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """subprocess.Popen() that never flashes a console window on Windows."""
    if "creationflags" in kwargs:
        kwargs["creationflags"] = _flags(kwargs["creationflags"])
    else:
        kwargs["creationflags"] = _flags()
    return subprocess.Popen(list(args), **kwargs)
