"""Bookmarks: read iOS Safari Bookmarks.db -> HTML bookmarks (Netscape format).

iOS 17+ Safari bookmarks schema (verified against a real backup):
  bookmarks(id, parent, type, title, url, ...)

  type = 0  -> a bookmark leaf (has a title + url)
  type = 1  -> a folder / list (e.g. Root, BookmarksBar, Reading List)

The standard interchange format for browser bookmarks is the Netscape
Bookmark HTML format (``<DT><A HREF=...>title</A>``), which the HUAWEI
browser can import directly. We only export leaf bookmarks that have a
non-empty URL; folders are flattened (their title is dropped), since the
HUAWEI browser import is flat.

Reading List entries (parent = com.apple.ReadingList) are skipped by
default, but can be included by setting ``include_reading_list=True``.
"""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def bookmarks_to_html(db_path: str | Path, include_reading_list: bool = False) -> str:
    """Export Safari bookmarks to Netscape HTML. Returns the HTML string."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Bookmarks database not found: {db}")

    with sqlite3.connect(str(db)) as conn:
        try:
            rows = conn.execute(
                "SELECT title, url, parent FROM bookmarks "
                "WHERE type = 0 AND url IS NOT NULL AND url != '' "
                "ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file.",
        "     It will be read and overwritten.",
        "     DO NOT EDIT! -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]

    count = 0
    for title, url, parent in rows:
        # Skip Reading List unless explicitly requested.
        if not include_reading_list and parent and "ReadingList" in str(parent):
            continue
        if not url:
            continue
        lines.append(f'    <DT><A HREF="{_esc(url)}">{_esc(title) or _esc(url)}</A>')
        count += 1

    lines.append("</DL><p>")
    return "\n".join(lines) + "\n"


def write_bookmarks(db_path: str | Path, out_path: str | Path) -> int:
    """Export bookmarks and write HTML to out_path. Returns bookmark count."""
    text = bookmarks_to_html(db_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text.count("<DT><A HREF=")
