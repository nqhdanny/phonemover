"""Unit tests for notes / bookmarks / reminders parsers (no device needed)."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.parse.bookmarks import bookmarks_to_html, write_bookmarks
from core.parse.notes import notes_to_text, write_notes
from core.parse.reminders import reminders_to_ics, write_reminders

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _apple(seconds: float) -> float:
    """Return Apple-epoch seconds for a timedelta from the epoch."""
    return seconds


def make_notes(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE ZNOTE (Z_PK INTEGER, ZTITLE TEXT, ZCREATIONDATE REAL, ZMODIFICATIONDATE REAL)"
    )
    conn.execute(
        "CREATE TABLE ZNOTEBODY (Z_PK INTEGER, ZNOTE INTEGER, ZHTMLSTRING TEXT)"
    )
    conn.execute("INSERT INTO ZNOTE VALUES (1, 'Grocery', 0, 0)")
    conn.execute("INSERT INTO ZNOTE VALUES (2, 'Ideas', 0, 0)")
    conn.execute("INSERT INTO ZNOTEBODY VALUES (1, 1, '<p>milk and eggs</p>')")
    conn.execute("INSERT INTO ZNOTEBODY VALUES (2, 2, 'build a <b>mover</b>')")
    conn.commit()
    conn.close()
    return path


def make_bookmarks(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE bookmarks (id INTEGER, parent INTEGER, type INTEGER, title TEXT, url TEXT)"
    )
    conn.execute("INSERT INTO bookmarks VALUES (0, NULL, 1, 'Root', NULL)")
    conn.execute("INSERT INTO bookmarks VALUES (1, 0, 1, 'BookmarksBar', '')")
    conn.execute(
        "INSERT INTO bookmarks VALUES (2, 1, 0, 'Example', 'https://example.com')"
    )
    conn.execute(
        "INSERT INTO bookmarks VALUES (3, 1, 0, 'Foo & Bar', 'https://foo.com?a=1&b=2')"
    )
    conn.execute(
        "INSERT INTO bookmarks VALUES (4, 2, 0, 'Reading Item', 'https://read.com')"
    )
    conn.commit()
    conn.close()
    return path


def make_reminders(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE ZREMCDREMINDER (Z_PK INTEGER, ZTITLE TEXT, ZNOTES TEXT, "
        "ZDUEDATE REAL, ZCOMPLETED INTEGER, ZCOMPLETIONDATE REAL, ZCREATIONDATE REAL, ZLIST INTEGER)"
    )
    conn.execute(
        "CREATE TABLE ZREMCDBASELIST (Z_PK INTEGER, ZNAME TEXT)"
    )
    conn.execute("INSERT INTO ZREMCDBASELIST VALUES (10, 'Personal')")
    due = 3600.0
    created = 0.0
    conn.execute(
        "INSERT INTO ZREMCDREMINDER VALUES (1, 'Buy milk', '2%', ?, 0, NULL, ?, 10)",
        (due, created),
    )
    conn.execute(
        "INSERT INTO ZREMCDREMINDER VALUES (2, 'Call mom', NULL, NULL, 1, 7200.0, 0.0, NULL)"
    )
    conn.commit()
    conn.close()
    return path


class TestNotes(unittest.TestCase):
    def test_notes_to_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_notes(Path(tmp) / "notes.sqlite")
            text = notes_to_text(db)
            self.assertIn("# Grocery", text)
            self.assertIn("milk and eggs", text)
            self.assertIn("# Ideas", text)
            self.assertIn("build a mover", text)  # HTML tags stripped
            self.assertNotIn("<b>", text)

    def test_write_notes_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_notes(Path(tmp) / "notes.sqlite")
            out = Path(tmp) / "notes.txt"
            n = write_notes(db, out)
            self.assertEqual(n, 2)
            self.assertTrue(out.exists())

    def test_missing_db_raises(self):
        with self.assertRaises(FileNotFoundError):
            notes_to_text("/nonexistent/notes.sqlite")


class TestBookmarks(unittest.TestCase):
    def test_bookmarks_to_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_bookmarks(Path(tmp) / "Bookmarks.db")
            html = bookmarks_to_html(db)
            self.assertIn("https://example.com", html)
            self.assertIn("Foo &amp; Bar", html)  # escaped
            self.assertIn("https://foo.com?a=1&amp;b=2", html)
            # folder rows (type=1) are excluded
            self.assertNotIn("BookmarksBar", html)
            self.assertNotIn(">Root<", html)

    def test_write_bookmarks_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_bookmarks(Path(tmp) / "Bookmarks.db")
            out = Path(tmp) / "bookmarks.html"
            n = write_bookmarks(db, out)
            self.assertEqual(n, 3)  # 3 leaf bookmarks
            self.assertTrue(out.exists())

    def test_missing_db_raises(self):
        with self.assertRaises(FileNotFoundError):
            bookmarks_to_html("/nonexistent/Bookmarks.db")


class TestReminders(unittest.TestCase):
    def test_reminders_to_ics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_reminders(Path(tmp) / "Data-local.sqlite")
            ics = reminders_to_ics([db])
            self.assertIn("BEGIN:VCALENDAR", ics)
            self.assertIn("BEGIN:VTODO", ics)
            self.assertIn("SUMMARY:[Personal] Buy milk", ics)
            self.assertIn("DESCRIPTION:2%", ics)
            self.assertIn("STATUS:NEEDS-ACTION", ics)
            self.assertIn("STATUS:COMPLETED", ics)
            self.assertEqual(ics.count("BEGIN:VTODO"), 2)

    def test_write_reminders_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_reminders(Path(tmp) / "Data-local.sqlite")
            out = Path(tmp) / "reminders.ics"
            n = write_reminders([db], out)
            self.assertEqual(n, 2)
            self.assertTrue(out.exists())

    def test_empty_reminders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "empty.sqlite"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "CREATE TABLE ZREMCDREMINDER (Z_PK INTEGER, ZTITLE TEXT, ZNOTES TEXT, "
                "ZDUEDATE REAL, ZCOMPLETED INTEGER, ZCOMPLETIONDATE REAL, ZCREATIONDATE REAL, ZLIST INTEGER)"
            )
            conn.commit()
            conn.close()
            ics = reminders_to_ics([db])
            self.assertNotIn("BEGIN:VTODO", ics)


if __name__ == "__main__":
    unittest.main()
