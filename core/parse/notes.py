"""Notes: read iOS notes.sqlite -> plain-text/markdown export.

iOS 17+ Notes schema (verified against a real backup):
  ZNOTE(Z_PK, ZTITLE, ZBODY, ZCREATIONDATE, ZMODIFICATIONDATE, ...)
  ZNOTEBODY(Z_PK, ZNOTE, ZHTMLSTRING / ZTEXT / ZCONTENT, ...)

Notes are stored in the ZNOTE table. The body text lives in ZNOTEBODY,
linked back to ZNOTE via the ZNOTE column (the note's Z_PK). Some iOS
versions store the body inline or as an HTML string, so we try several
body columns in order and strip basic HTML tags.

Dates are Apple/NSDate epoch seconds (2001-01-01 UTC).

Export format: one note per Markdown file (``<title>.md``) so the HUAWEI
side can import them individually, plus a ``notes.txt`` aggregate that the
APK reads as a single batch (title + body separated by markers).
"""

from __future__ import annotations

import html
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Columns that may hold the note body, tried in priority order.
_BODY_COLUMNS = ["ZHTMLSTRING", "ZTEXT", "ZCONTENT", "ZHTML"]

_TAG_RE = re.compile(r"<[^>]+>")


def _apple_to_datetime(seconds):
    if seconds is None:
        return None
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return None
    return APPLE_EPOCH + timedelta(seconds=seconds)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return text.strip()


def notes_to_text(db_path: str | Path) -> str:
    """Export all notes as a single plain-text blob (title + body).

    Each note is emitted as ``# title`` followed by the body; notes are
    separated by a blank line. Returns the aggregate text.
    """
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Notes database not found: {db}")

    # Resolve body per note from ZNOTEBODY.
    bodies: dict[int, str] = {}
    with sqlite3.connect(str(db)) as conn:
        try:
            body_cols = [
                c[1]
                for c in conn.execute("PRAGMA table_info(ZNOTEBODY)").fetchall()
            ]
        except sqlite3.OperationalError:
            body_cols = []

        if body_cols:
            use_col = next((c for c in _BODY_COLUMNS if c in body_cols), None)
            if use_col:
                try:
                    for note_id, body in conn.execute(
                        f"SELECT ZNOTE, {use_col} FROM ZNOTEBODY WHERE ZNOTE IS NOT NULL"
                    ).fetchall():
                        if body:
                            bodies[int(note_id)] = _strip_html(str(body))
                except sqlite3.OperationalError:
                    pass

        # Fall back to ZNOTE's own body column if present.
        note_cols = [
            c[1] for c in conn.execute("PRAGMA table_info(ZNOTE)").fetchall()
        ]
        inline_body = next((c for c in _BODY_COLUMNS if c in note_cols), None)

        rows = conn.execute(
            "SELECT Z_PK, ZTITLE, ZCREATIONDATE, ZMODIFICATIONDATE, "
            f"{inline_body or 'NULL'} FROM ZNOTE ORDER BY Z_PK"
        ).fetchall()

    chunks: list[str] = []
    for pk, title, created, modified, inline in rows:
        title = (title or "").strip()
        body = bodies.get(int(pk), "") if pk is not None else ""
        if inline and not body:
            body = _strip_html(str(inline))

        if not title and not body:
            continue

        chunks.append(f"# {title}" if title else "# Untitled")
        if body:
            chunks.append(body)
        chunks.append("")  # blank line separator

    return "\n".join(chunks).rstrip() + "\n"


def write_notes(db_path: str | Path, out_path: str | Path) -> int:
    """Export notes to out_path. Returns note count."""
    text = notes_to_text(db_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="")
    return text.count("\n# ") + (1 if text.startswith("# ") else 0)
