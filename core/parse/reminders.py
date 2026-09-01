"""Reminders: read iOS Reminders CoreData sqlite -> ICS/plain-text.

iOS 17+ Reminders store their data in CoreData sqlite files under
``AppDomainGroup-group.com.apple.reminders/Container_v1/Stores/*.sqlite``.
There is one file per account plus a ``Data-local.sqlite`` for locally-stored
(not-yet-iCloud-synced) reminders. The reminder rows live in:

  ZREMCDREMINDER(Z_PK, ZTITLE, ZNOTES, ZDUEDATE, ZCOMPLETED,
                 ZCOMPLETIONDATE, ZCREATIONDATE, ZLIST, ...)
  ZREMCDBASELIST(Z_PK, ZNAME, ...)   # the list a reminder belongs to

ZLIST in ZREMCDREMINDER is a foreign key (Z_PK of the list). ZDUEDATE /
ZCOMPLETIONDATE / ZCREATIONDATE are Apple/NSDate epoch seconds (2001-01-01
UTC). ZCOMPLETED is a boolean.

Export format: the HUAWEI side has no direct Reminders provider we can write
to without root, so we convert reminders into iCalendar VTODO entries (the
standard cross-platform format) which the importer APK turns into calendar
events or note-style reminders. We also emit a plain-text aggregate for the
fallback "dump to notes" path.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _apple_to_datetime(seconds):
    if seconds is None:
        return None
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return None
    return APPLE_EPOCH + timedelta(seconds=seconds)


def _format_dt(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _esc(text) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _read_one(db_path: Path, list_names: dict[int, str]) -> list[dict]:
    """Read reminders from a single CoreData sqlite file."""
    out: list[dict] = []
    if not db_path.exists():
        return out

    with sqlite3.connect(str(db_path)) as conn:
        # Resolve list names.
        try:
            for pk, name in conn.execute(
                "SELECT Z_PK, ZNAME FROM ZREMCDBASELIST WHERE ZNAME IS NOT NULL"
            ).fetchall():
                list_names[int(pk)] = str(name)
        except sqlite3.OperationalError:
            pass

        try:
            rows = conn.execute(
                "SELECT Z_PK, ZTITLE, ZNOTES, ZDUEDATE, ZCOMPLETED, "
                "ZCOMPLETIONDATE, ZCREATIONDATE, ZLIST "
                "FROM ZREMCDREMINDER ORDER BY Z_PK"
            ).fetchall()
        except sqlite3.OperationalError:
            return out

        for pk, title, notes, due, completed, completed_at, created, list_id in rows:
            if not title and not notes:
                continue
            out.append(
                {
                    "pk": int(pk) if pk is not None else 0,
                    "title": (title or "").strip(),
                    "notes": (notes or "").strip(),
                    "due": _apple_to_datetime(due),
                    "completed": bool(completed),
                    "completed_at": _apple_to_datetime(completed_at),
                    "created": _apple_to_datetime(created),
                    "list": list_names.get(int(list_id)) if list_id is not None else None,
                }
            )
    return out


def reminders_to_ics(db_paths: list[str | Path]) -> str:
    """Export reminders from one or more CoreData sqlite files to iCalendar VTODO."""
    list_names: dict[int, str] = {}
    items: list[dict] = []
    for p in db_paths:
        items.extend(_read_one(Path(p), list_names))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PhoneMover//Reminders Export//EN",
        "CALSCALE:GREGORIAN",
    ]

    for it in items:
        lines.append("BEGIN:VTODO")
        lines.append(f"UID:ios-rem-{it['pk']}")
        lines.append(f"DTSTAMP:{_format_dt(datetime.now(timezone.utc))}")
        if it["created"]:
            lines.append(f"CREATED:{_format_dt(it['created'])}")
        if it["due"]:
            lines.append(f"DUE:{_format_dt(it['due'])}")
        if it["completed_at"]:
            lines.append(f"COMPLETED:{_format_dt(it['completed_at'])}")

        summary = it["title"] or "(No Title)"
        if it["list"]:
            summary = f"[{it['list']}] {summary}"
        lines.append(f"SUMMARY:{_esc(summary)}")
        if it["notes"]:
            lines.append(f"DESCRIPTION:{_esc(it['notes'])}")

        status = "COMPLETED" if it["completed"] else "NEEDS-ACTION"
        lines.append(f"STATUS:{status}")
        lines.append("END:VTODO")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_reminders(db_paths: list[str | Path], out_path: str | Path) -> int:
    """Export reminders to an .ics file. Returns reminder count."""
    text = reminders_to_ics(db_paths)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="")
    return text.count("BEGIN:VTODO")
