"""Calendar: read iOS Calendar.sqlitedb -> .ics (iCalendar 2.0).

iOS 17+ calendar schema (verified against a real backup):
  CalendarItem(ROWID, summary, location_id, description, start_date,
               end_date, all_day, calendar_id, ...)
    # NOTE: notes -> description; location is a FK (location_id) into Location
  Calendar(ROWID, store_id, title, ...)
  Location(ROWID, title, address, ...)

Dates are stored as seconds since 2001-01-01 (Apple/NSDate epoch); UTC is
assumed for the .ics DTSTAMP/DTSTART/DTEND. All-day events use DTSTART;VALUE=DATE.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Apple NSDate epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _apple_to_datetime(seconds) -> datetime | None:
    if seconds is None:
        return None
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return None
    return APPLE_EPOCH + timedelta(seconds=seconds)


def _format_dt(dt) -> str:
    """Format as iCalendar UTC datetime (YYYYMMDDTHHMMSSZ)."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _format_date(dt) -> str:
    """Format as iCalendar DATE (YYYYMMDD) for all-day events."""
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d")


def _esc(text) -> str:
    """Escape a text value for iCalendar content lines."""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def calendar_to_ics(db_path: str | Path) -> str:
    """Export all events from Calendar.sqlitedb as one iCalendar blob."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Calendar database not found: {db}")

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PhoneMover//Calendar Export//EN",
        "CALSCALE:GREGORIAN",
    ]

    with sqlite3.connect(str(db)) as conn:
        # Resolve calendar titles (optional, tolerate missing schema).
        cal_names: dict[int, str] = {}
        try:
            for rowid, title in conn.execute(
                "SELECT ROWID, title FROM Calendar"
            ).fetchall():
                if title:
                    cal_names[rowid] = str(title)
        except sqlite3.OperationalError:
            pass

        # Resolve location titles via location_id -> Location(ROWID, title).
        loc_names: dict[int, str] = {}
        try:
            for rowid, title in conn.execute(
                "SELECT ROWID, title FROM Location"
            ).fetchall():
                if title:
                    loc_names[rowid] = str(title)
        except sqlite3.OperationalError:
            pass

        try:
            rows = conn.execute(
                """
                SELECT ROWID, summary, location_id, description, start_date,
                       end_date, all_day, calendar_id
                FROM CalendarItem
                ORDER BY start_date
                """
            ).fetchall()
        except sqlite3.OperationalError:
            # Some backups omit the table entirely.
            rows = []

        for rowid, summary, loc_id, description, start, end, all_day, cal_id in rows:
            start_dt = _apple_to_datetime(start)
            end_dt = _apple_to_datetime(end)
            if start_dt is None:
                continue

            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:ios-{rowid}")
            lines.append(f"DTSTAMP:{_format_dt(datetime.now(timezone.utc))}")

            if all_day:
                lines.append(f"DTSTART;VALUE=DATE:{_format_date(start_dt)}")
                end_dt = end_dt or (start_dt + timedelta(days=1))
                lines.append(f"DTEND;VALUE=DATE:{_format_date(end_dt)}")
            else:
                lines.append(f"DTSTART:{_format_dt(start_dt)}")
                if end_dt:
                    lines.append(f"DTEND:{_format_dt(end_dt)}")

            lines.append(f"SUMMARY:{_esc(summary)}")
            # location_id -> Location title
            loc_title = loc_names.get(loc_id) if loc_id else None
            if loc_title:
                lines.append(f"LOCATION:{_esc(loc_title)}")
            if description:
                lines.append(f"DESCRIPTION:{_esc(description)}")
            if cal_id in cal_names:
                lines.append(f"CATEGORIES:{_esc(cal_names[cal_id])}")
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics(db_path: str | Path, out_path: str | Path) -> int:
    """Export calendar and write to out_path. Returns event count."""
    text = calendar_to_ics(db_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="")
    return text.count("BEGIN:VEVENT")
