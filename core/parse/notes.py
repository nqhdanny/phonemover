"""Notes: read iOS Notes database -> plain-text export.

iOS 17+ stores notes in a CoreData database whose schema changed from the
legacy ``ZNOTE``/``ZNOTEBODY`` tables to:

  ZICCLOUDSYNCINGOBJECT  (single-table CoreData inheritance)
      Z_ENT = 12          -> a note object
      ZTITLE1              -> note title
      ZSNIPPET             -> plain-text snippet (also used as body fallback)
      ZWIDGETSNIPPET       -> widget snippet
  ZICNOTEDATA
      ZNOTE                -> FK to the note object's Z_PK
      ZDATA                -> gzip/zlib-compressed NSAttributedString

Two database locations exist across iOS versions:
  * New (iOS 17+):  AppDomainGroup-group.com.apple.notes/NoteStore.sqlite
  * Legacy:         HomeDomain/Library/Notes/notes.sqlite  (ZNOTE table)

We support both. For the new schema the title comes from ``ZTITLE1``; the body
is decompressed from ``ZICNOTEDATA.ZDATA`` and the embedded UTF-8 text is
extracted heuristically (the NSAttributedString archive is binary, but its
NSString content is recoverable as readable runs). When no body is recoverable
we fall back to ``ZSNIPPET``.

Dates are Apple/NSDate epoch seconds (2001-01-01 UTC). The export is a single
plain-text blob: one ``# title`` line then the body, blank-line separated.
"""

from __future__ import annotations

import gzip
import re
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Legacy schema body columns (tried in order).
_LEGACY_BODY_COLUMNS = ["ZHTMLSTRING", "ZTEXT", "ZCONTENT", "ZHTML"]

_TAG_RE = re.compile(r"<[^>]+>")


def _decompress(data: bytes) -> bytes:
    """Decompress gzip (1f 8b) or zlib (78 9c/78 da) data."""
    if not data:
        return b""
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if data[:2] in (b"\x78\x9c", b"\x78\xda", b"\x78\x01"):
        return zlib.decompress(data)
    return data


def _extract_text(blob: bytes) -> str:
    """Extract readable text runs from a decompressed NSAttributedString.

    The binary NSAttributedString archive embeds the note's NSString content
    near the start, followed by a dictionary of attributes (which looks like
    noise: short numeric/hex runs, single letters, etc.). We keep only runs
    that contain CJK or >=2 consecutive letters and drop short/numeric junk.
    """
    if not blob:
        return ""
    raw = _decompress(blob)
    dec = raw.decode("utf-8", errors="ignore")

    # Candidate runs: letters/digits/CJK + common punctuation/whitespace.
    runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\s,\.\?!;:()\-'\"\u00e0-\u00ff]{1,}", dec)

    kept: list[str] = []
    for r in runs:
        s = r.strip()
        if not s:
            continue
        # Drop fragments with control chars (binary noise like "s\x1et").
        if any(ord(ch) < 32 for ch in s):
            continue
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in s)
        letters = sum(1 for ch in s if ch.isalpha())
        digits = sum(1 for ch in s if ch.isdigit())
        if has_cjk:
            kept.append(s)
        elif letters >= 2 and len(s) >= 2:
            if digits and " " not in s and len(s) <= 6:
                continue
            kept.append(s)

    return "\n".join(kept)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    import html as _html

    text = _TAG_RE.sub("", text)
    return _html.unescape(text).strip()


def _read_legacy(db_path: Path) -> list[tuple[str, str]]:
    """Read notes from the legacy ZNOTE/ZNOTEBODY schema."""
    out: list[tuple[str, str]] = []
    with sqlite3.connect(str(db_path)) as conn:
        body_cols = [
            c[1] for c in conn.execute("PRAGMA table_info(ZNOTEBODY)").fetchall()
        ]
        bodies: dict[int, str] = {}
        if body_cols:
            use_col = next((c for c in _LEGACY_BODY_COLUMNS if c in body_cols), None)
            if use_col:
                try:
                    for note_id, body in conn.execute(
                        f"SELECT ZNOTE, {use_col} FROM ZNOTEBODY WHERE ZNOTE IS NOT NULL"
                    ).fetchall():
                        if body:
                            bodies[int(note_id)] = _strip_html(str(body))
                except sqlite3.OperationalError:
                    pass

        note_cols = [c[1] for c in conn.execute("PRAGMA table_info(ZNOTE)").fetchall()]
        inline = next((c for c in _LEGACY_BODY_COLUMNS if c in note_cols), None)
        try:
            rows = conn.execute(
                f"SELECT Z_PK, ZTITLE, {inline or 'NULL'} FROM ZNOTE ORDER BY Z_PK"
            ).fetchall()
        except sqlite3.OperationalError:
            return out

        for pk, title, inline_body in rows:
            title = (title or "").strip()
            body = bodies.get(int(pk), "") if pk is not None else ""
            if inline_body and not body:
                body = _strip_html(str(inline_body))
            if title or body:
                out.append((title or "Untitled", body))
    return out


def _read_new(db_path: Path) -> list[tuple[str, str]]:
    """Read notes from the iOS 17+ ZICCLOUDSYNCINGOBJECT schema."""
    out: list[tuple[str, str]] = []
    with sqlite3.connect(str(db_path)) as conn:
        bodies: dict[int, str] = {}
        try:
            for _pk, note_fk, zdata in conn.execute(
                "SELECT Z_PK, ZNOTE, ZDATA FROM ZICNOTEDATA WHERE ZDATA IS NOT NULL"
            ).fetchall():
                if note_fk is None:
                    continue
                text = _extract_text(zdata) if zdata else ""
                if text:
                    bodies[int(note_fk)] = text
        except sqlite3.OperationalError:
            pass

        try:
            rows = conn.execute(
                "SELECT Z_PK, ZTITLE1, ZSNIPPET FROM ZICCLOUDSYNCINGOBJECT "
                "WHERE Z_ENT = 12 ORDER BY Z_PK"
            ).fetchall()
        except sqlite3.OperationalError:
            return out

        for pk, title, snippet in rows:
            title = (title or "").strip()
            body = bodies.get(int(pk), "") if pk is not None else ""
            if not body and snippet:
                body = str(snippet).strip()
            if title or body:
                out.append((title or "Untitled", body))
    return out


def read_notes(db_path: str | Path) -> list[dict]:
    """Read notes as structured records for per-note import.

    Unlike :func:`notes_to_text` (which flattens everything into one blob),
    this returns one dict per note so the HUAWEI importer can push each note
    into the Notepad app individually via ``ACTION_SEND``:

        {"title": str, "body": str}

    The ``title`` is the iOS note title; when iOS leaves it empty the first
    line of the body is promoted to the title (HUAWEI Notepad derives its own
    title from the content, but a title helps the user identify the note).
    Notes with neither title nor body are skipped.
    """
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Notes database not found: {db}")

    notes = _read_new(db)
    if not notes:
        notes = _read_legacy(db)

    out: list[dict] = []
    for title, body in notes:
        title = (title or "").strip()
        body = (body or "").strip()
        if not title and not body:
            continue
        # iOS often stores an empty title and relies on the first body line.
        if not title:
            first_line = body.splitlines()[0].strip() if body else ""
            title = first_line[:40] if first_line else "Untitled"
        out.append({"title": title, "body": body})
    return out


def notes_to_text(db_path: str | Path) -> str:
    """Export all notes as one plain-text blob (``# title`` + body)."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Notes database not found: {db}")

    notes = _read_new(db)
    if not notes:
        notes = _read_legacy(db)

    chunks: list[str] = []
    for title, body in notes:
        chunks.append(f"# {title}")
        if body:
            chunks.append(body)
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def write_notes(db_path: str | Path, out_path: str | Path) -> int:
    """Export notes to out_path. Returns note count."""
    text = notes_to_text(db_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="")
    return text.count("\n# ") + (1 if text.startswith("# ") else 0)


def write_notes_json(db_path: str | Path, out_path: str | Path) -> int:
    """Export notes as JSON (one object per note). Returns note count.

    This is the machine-readable companion to :func:`write_notes`, consumed by
    the HUAWEI Notepad importer so it can import notes one by one instead of
    shipping a single opaque text blob.
    """
    import json

    notes = read_notes(db_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8", newline=""
    )
    return len(notes)
