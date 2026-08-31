"""Backup engine — wraps `pymobiledevice3 backup2` as a subprocess.

Strategy: delegate the heavy lifting (pairing, lockdown, mobilebackup2
protocol) to the battle-tested pymobiledevice3 CLI, parse its progress
output, and expose a callback-friendly API.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ProgressCB = Callable[[int, str], None]  # (percent 0-100, stage message)


@dataclass
class BackupResult:
    ok: bool
    dest_dir: Path
    encrypted: bool = False
    message: str = ""
    files_copied: int = 0


# pymobiledevice3 prints progress like: "  42%  ..." (best-effort parsing)
_PROGRESS_RE = re.compile(r"(\d{1,3})%")


def _parse_progress(line: str) -> Optional[int]:
    m = _PROGRESS_RE.search(line)
    if m:
        return min(int(m.group(1)), 100)
    return None


def _default_python() -> str:
    return sys.executable


def backup_full(
    dest_dir: str | Path,
    udid: Optional[str] = None,
    password: Optional[str] = None,
    progress_cb: Optional[ProgressCB] = None,
    python_bin: str | None = None,
) -> BackupResult:
    """Create a full iPhone backup into dest_dir.

    - udid: optional, back up a specific device when several are connected.
    - password: passphrase for encrypted backups (if the user enabled it).
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    cmd = [python_bin or _default_python(), "-m", "pymobiledevice3", "backup2", "backup"]
    if udid:
        cmd += ["-u", udid]
    cmd += ["--full", str(dest)]
    if password:
        cmd += ["--password", password]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None

    result = BackupResult(ok=False, dest_dir=dest)
    log_lines: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        log_lines.append(line)
        pct = _parse_progress(line)
        if pct is not None and progress_cb:
            progress_cb(pct, line.strip())
        elif progress_cb:
            # stage lines without percent
            progress_cb(None if not log_lines else 0, line.strip())  # type: ignore[arg-type]

    proc.wait()
    if proc.returncode == 0:
        result.ok = True
        result.encrypted = bool(password)
        result.message = f"Backup completed at {dest}"
    else:
        result.message = f"Backup failed (exit {proc.returncode}): {log_lines[-3:] if log_lines else 'no output'}"
    return result


def estimate_backup_size(dest_dir: str | Path) -> int:
    """Total bytes already in a backup directory (for UI display)."""
    dest = Path(dest_dir)
    if not dest.exists():
        return 0
    return sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())


def available_disk_space(dest_dir: str | Path) -> int:
    return shutil.disk_usage(str(dest_dir)).free
