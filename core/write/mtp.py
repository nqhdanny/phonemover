"""MTP/media writer.

On Windows the HUAWEI phone appears as a removable drive (e.g. F:\\) via MTP;
media is copied into DCIM/Camera, Music, etc. On Linux (dev/test) we copy into
a plain directory tree that mirrors the MTP layout, so the same code runs in CI.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

ProgressCB = Callable[[int, str], None]


def copy_media_tree(
    src_dir: str | Path,
    dest_root: str | Path,
    subdir: str = "DCIM/Camera",
    progress_cb: Optional[ProgressCB] = None,
) -> int:
    """Copy all files under src_dir into dest_root/subdir. Returns count."""
    src = Path(src_dir)
    dest = Path(dest_root) / subdir
    dest.mkdir(parents=True, exist_ok=True)

    files = [f for f in src.rglob("*") if f.is_file()]
    total = len(files)
    for i, f in enumerate(files, start=1):
        shutil.copy2(f, dest / f.name)
        if progress_cb and (i % 25 == 0 or i == total):
            progress_cb(int(i / total * 100) if total else 100, f"copy {i}/{total}")
    return total


def write_text_file(text: str, dest_path: str | Path) -> None:
    """Write a text artifact (e.g. vCards for the APK channel)."""
    p = Path(dest_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
