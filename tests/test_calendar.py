"""Unit tests for calendar parser (no real device needed)."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.parse.calendar import calendar_to_ics, write_ics

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def make_calendar(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE Calendar (ROWID INTEGER, title TEXT, color TEXT)"
    )
    conn.execute(
        """
        CREATE TABLE CalendarItem (
            ROWID INTEGER, summary TEXT, location TEXT, start_date REAL,
            end_date REAL, all_day INTEGER, calendar_id INTEGER, notes TEXT
        )
        """
    )
    conn.execute("INSERT INTO Calendar VALUES (1, 'Work', NULL)")
    start = (APPLE_EPOCH + timedelta(hours=9)).timestamp() - APPLE_EPOCH.timestamp()
    end = start + 3600
    conn.execute(
        "INSERT INTO CalendarItem VALUES (100, 'Team sync', 'Room 4', ?, ?, 0, 1, 'weekly')",
        (start, end),
    )
    # all-day event
    all_start = (APPLE_EPOCH + timedelta(days=5)).timestamp() - APPLE_EPOCH.timestamp()
    conn.execute(
        "INSERT INTO CalendarItem VALUES (101, 'Holiday', NULL, ?, NULL, 1, NULL, NULL)",
        (all_start,),
    )
    conn.commit()
    conn.close()
    return path


class TestCalendar(unittest.TestCase):
    def test_ics_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_calendar(Path(tmp) / "Calendar.sqlitedb")
            text = calendar_to_ics(db)
            self.assertIn("BEGIN:VCALENDAR", text)
            self.assertIn("VERSION:2.0", text)
            self.assertIn("SUMMARY:Team sync", text)
            self.assertIn("LOCATION:Room 4", text)
            self.assertIn("CATEGORIES:Work", text)
            self.assertIn("DESCRIPTION:weekly", text)
            self.assertIn("DTSTART:", text)
            self.assertIn("DTEND:", text)
            # all-day event uses DATE value type
            self.assertIn("DTSTART;VALUE=DATE:", text)
            self.assertEqual(text.count("BEGIN:VEVENT"), 2)

    def test_write_ics_returns_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_calendar(Path(tmp) / "Calendar.sqlitedb")
            out = Path(tmp) / "calendar.ics"
            n = write_ics(db, out)
            self.assertEqual(n, 2)
            self.assertTrue(out.exists())
            self.assertIn("BEGIN:VCALENDAR", out.read_text(encoding="utf-8"))

    def test_missing_db_raises(self):
        with self.assertRaises(FileNotFoundError):
            calendar_to_ics("/nonexistent/Calendar.sqlitedb")


if __name__ == "__main__":
    unittest.main()
