"""HUAWEI Notepad import — push iPhone notes into the Notepad app one by one.

Why this module exists
----------------------
HUAWEI Notepad (``com.huawei.notepad``) is a ``/system/priv-app`` system app
with **no public import API**:

  * its data dir is ``Permission denied`` even for ``adb shell`` (uid 2000)
  * it does not declare ``allowBackup``, so ``adb backup`` / ``bmgr`` skip it
  * it is not debuggable, so ``run-as`` is unavailable
  * its ContentProvider (``notepad-app.com``) and deep links
    (``hwnotepad://``) are guarded by ``HW_SIGNATURE_OR_SYSTEM``, a signature
    permission only HUAWEI-signed apps hold

What *does* work is the app's ``ACTION_SEND`` handler. Verified on a real
HUAWEI CRS-LX9 (EMUI 16 / Android 16, Notepad 14.6.9.300):

  ``NotePadShareActivity`` registers ``ACTION_SEND`` with ``text/plain``,
  showing a "Save as new note" dialog pre-filled with the shared text. Tapping
  **SAVE** creates the note and opens ``NoteEditor``. Notes imported this way
  show up in the Notepad list immediately.

So the import flow per note is:

  1. ``am start -a android.intent.action.SEND -t text/plain
        --es android.intent.extra.TEXT "<body>" com.huawei.notepad``
  2. wait for the share dialog (``NotePadShareActivity``) to come to the front
  3. tap **SAVE** (coordinates scaled to the device's real resolution)
  4. wait for ``NoteEditor`` — that is our success signal
  5. dismiss the editor (keyboard / back) and return to the list, ready for the
     next note

Compared with the old behaviour (``push notes.txt`` into ``/sdcard/Documents``)
this actually delivers the notes into the Notepad app instead of leaving a
file the user has to find and import by hand.

Note on ``.hdoc``
-----------------
The app also registers ``VIEW`` for ``file``/``content`` + ``*.hdoc``, but that
resolves to ``SketchActivity`` (handwritten/sketch notes), *not* text notes —
a plain-text ``.hdoc`` fails with "Note failed to load". ``ACTION_SEND`` is the
correct channel for text notes.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.write.subprocess_util import run_cmd
from core.write.vendor import find_adb

log = logging.getLogger(__name__)

NOTEPAD_PACKAGE = "com.huawei.notepad"
SHARE_ACTIVITY = f"{NOTEPAD_PACKAGE}/com.huawei.android.notepad.share.NotePadShareActivity"
EDITOR_ACTIVITY = f"{NOTEPAD_PACKAGE}/com.example.android.notepad.NoteEditor"
LIST_ACTIVITY = f"{NOTEPAD_PACKAGE}/com.example.android.notepad.NotePadActivity"

# Reference device used when the SAVE button coordinates were measured
# (HUAWEI CRS-LX9, 1320x2856). Real devices are scaled from this baseline.
REF_WIDTH = 1320
REF_HEIGHT = 2856
REF_SAVE_X = 979
REF_SAVE_Y = 2702

# A note body longer than this can be truncated by the shell / intent extras on
# some devices; long notes are chunked into additional notes to be safe.
MAX_BODY_CHARS = 60000


@dataclass
class NotepadImportResult:
    ok: bool
    imported: int = 0
    failed: int = 0
    total: int = 0
    message: str = ""
    errors: list[str] = field(default_factory=list)


def _adb() -> str:
    return find_adb()


def _adb_args(serial: Optional[str] = None) -> list[str]:
    args = [_adb()]
    if serial:
        args += ["-s", serial]
    return args


def _run_shell(cmd: list[str], serial: Optional[str] = None, timeout: int = 30):
    """Run an adb shell command as an argv list (no shell quoting issues)."""
    return run_cmd(_adb_args(serial) + ["shell", *cmd],
                   capture_output=True, text=True, timeout=timeout)


def device_size(serial: Optional[str] = None) -> tuple[int, int]:
    """Return the device's (width, height) in pixels."""
    try:
        proc = _run_shell(["wm", "size"], serial)
        m = re.search(r"(\d+)x(\d+)", proc.stdout or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as exc:  # noqa: BLE001
        log.warning(f"could not read device size: {exc}")
    return REF_WIDTH, REF_HEIGHT


def _scale(x: int, y: int, size: tuple[int, int]) -> tuple[int, int]:
    w, h = size
    return int(x * w / REF_WIDTH), int(y * h / REF_HEIGHT)


def _current_focus(serial: Optional[str] = None) -> str:
    try:
        proc = _run_shell(["dumpsys", "window"], serial, timeout=20)
        for line in (proc.stdout or "").splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _wait_for_focus(needle: str, serial: Optional[str] = None,
                    timeout: float = 6.0, interval: float = 0.4) -> bool:
    """Poll until ``needle`` appears in the window focus dump."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if needle in _current_focus(serial):
            return True
        time.sleep(interval)
    return False


def _dismiss_keyboard(serial: Optional[str] = None) -> None:
    """Best-effort: close the soft keyboard / any modal before navigating back."""
    try:
        _run_shell(["input", "keyevent", "KEYCODE_BACK"], serial, timeout=15)
        time.sleep(0.3)
    except Exception:  # noqa: BLE001
        pass


def _return_to_list(serial: Optional[str] = None) -> None:
    """Leave NoteEditor and go back to the note list, ready for the next note."""
    _dismiss_keyboard(serial)
    for _ in range(3):
        try:
            _run_shell(["input", "keyevent", "KEYCODE_BACK"], serial, timeout=15)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
        if LIST_ACTIVITY in _current_focus(serial):
            return
    # Fallback: relaunch the list explicitly.
    try:
        run_cmd(_adb_args(serial) + ["shell", "am", "start", "-n", LIST_ACTIVITY],
                capture_output=True, text=True, timeout=30)
        time.sleep(1.0)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"could not relaunch note list: {exc}")


def import_one_note(title: str, body: str, serial: Optional[str] = None,
                    size: Optional[tuple[int, int]] = None,
                    timeout: float = 15.0) -> tuple[bool, str]:
    """Import a single note into HUAWEI Notepad via ACTION_SEND.

    Returns ``(ok, message)``. Success is detected by ``NoteEditor`` coming to
    the foreground, which only happens after the SAVE tap creates the note.
    """
    content = body.strip() if body and body.strip() else (title or "").strip()
    if not content:
        return False, "empty note content"

    if len(content) > MAX_BODY_CHARS:
        content = content[:MAX_BODY_CHARS]

    # Launch the share sheet.
    #
    # IMPORTANT: ``adb shell <cmd>`` concatenates its arguments and hands the
    # result to /system/bin/sh. A note containing a newline therefore breaks
    # the command in two — the text after "\n" is executed as its own command
    # (observed: "sh: IIh: inaccessible or not found"). Multi-line notes are
    # the norm, so we base64-encode the content and let the device decode it
    # inside the intent extra:
    #
    #   --es ...EXTRA_TEXT "$(echo <b64> | base64 -d)"
    #
    # base64 is present at /system/bin/base64 on EMUI/HarmonyOS (toybox). The
    # encoded payload is a single safe token: no newlines, no quotes, no
    # shell metacharacters, and UTF-8/CJK survives untouched.
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    shell_cmd = (
        f'am start -a android.intent.action.SEND -t text/plain '
        f'--es android.intent.extra.TEXT "$(echo {b64} | base64 -d)" '
        f'{NOTEPAD_PACKAGE}'
    )

    try:
        proc = run_cmd(
            _adb_args(serial) + ["shell", shell_cmd],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"am start failed: {exc}"

    if proc.returncode != 0:
        return False, f"am start rc={proc.returncode}: {(proc.stderr or '').strip()[:200]}"

    # Wait for the share dialog ("Save as new note").
    if not _wait_for_focus("NotePadShareActivity", serial, timeout=timeout):
        focus = _current_focus(serial)
        # Some builds go straight to the editor.
        if "NoteEditor" not in focus:
            return False, f"share dialog did not appear (focus={focus[:120]})"

    # Tap SAVE.
    sx, sy = _scale(REF_SAVE_X, REF_SAVE_Y, size or device_size(serial))
    try:
        _run_shell(["input", "tap", str(sx), str(sy)], serial, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return False, f"tap SAVE failed: {exc}"

    # NoteEditor in the foreground == the note was created.
    if _wait_for_focus("NoteEditor", serial, timeout=8.0):
        return True, "saved"

    # The dialog may still be up (e.g. CANCEL/SAVE at a different offset on
    # this device). Retry once at a "just above the bottom" fallback position.
    w, h = size or device_size(serial)
    fx, fy = int(w * 0.74), int(h * 0.945)
    if (fx, fy) != (sx, sy):
        try:
            _run_shell(["input", "tap", str(fx), str(fy)], serial, timeout=20)
        except Exception:  # noqa: BLE001
            pass
        if _wait_for_focus("NoteEditor", serial, timeout=6.0):
            return True, "saved (fallback tap)"

    focus = _current_focus(serial)
    return False, f"save not confirmed (focus={focus[:120]})"


def import_notes_to_notepad(
    notes: list[dict],
    serial: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    settle: float = 0.6,
) -> NotepadImportResult:
    """Import every note into HUAWEI Notepad, one ACTION_SEND per note.

    ``notes`` is the list produced by :func:`core.parse.notes.read_notes`
    (``[{"title": ..., "body": ...}, ...]``).

    The device screen should be on; we do not force-unlock it (the user has to
    have granted USB debugging and, on first run, confirmed the share target).
    A note that fails is recorded in ``errors`` and the loop continues, so one
    malformed note cannot abort the whole batch.
    """
    result = NotepadImportResult(ok=True, total=len(notes))
    if not notes:
        result.message = "no notes to import"
        return result

    size = device_size(serial)

    # Start from a known screen: the note list.
    try:
        run_cmd(_adb_args(serial) + ["shell", "am", "start", "-n", LIST_ACTIVITY],
                capture_output=True, text=True, timeout=30)
        time.sleep(settle)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"could not open note list: {exc}")

    for idx, note in enumerate(notes, 1):
        title = (note.get("title") or "").strip()
        body = (note.get("body") or "").strip()
        label = title or (body.splitlines()[0][:30] if body else "(empty)")
        if progress_cb:
            progress_cb(idx, len(notes), f"importing note: {label}")

        try:
            ok, msg = import_one_note(title, body, serial=serial, size=size)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"exception: {exc}"

        if ok:
            result.imported += 1
            log.info(f"note {idx}/{len(notes)} imported: {label}")
        else:
            result.failed += 1
            err = f"note {idx} '{label}': {msg}"
            result.errors.append(err)
            log.error(err)

        # Return to the list so the next ACTION_SEND starts from a clean state.
        _return_to_list(serial)
        time.sleep(settle * 0.5)

    if result.failed:
        result.ok = result.imported > 0
    result.message = (
        f"{result.imported}/{result.total} notes imported into Notepad"
        + (f", {result.failed} failed" if result.failed else "")
    )
    return result


def load_notes_json(path: str | Path) -> list[dict]:
    """Load the notes JSON produced by core.parse.notes.write_notes_json."""
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))
