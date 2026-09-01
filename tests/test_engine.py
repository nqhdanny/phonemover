"""Unit tests for the migration engine (synthetic backup, no device)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.engine import MigrationEngine
from core.models import DataType


def _write_blob(root: Path, fid: str, data: bytes) -> None:
    """Write a blob using the sharded iOS layout: <root>/<fid[:2]>/<fid>."""
    blob = root / fid[:2] / fid
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)


def make_backup(root: Path) -> Path:
    """Build a minimal sharded backup with AddressBook + Calendar + media."""
    root.mkdir(parents=True, exist_ok=True)

    AB = "31bb7ba8914766d4ba40d6dfb6113c8b614be442"
    CAL = "2041457d5fe04d39d0ab481178355df6781e6858"
    PHOTO = "aa00000000000000000000000000000000000001"
    VIDEO = "bb00000000000000000000000000000000000002"

    # AddressBook.sqlitedb (real iOS 17+ schema)
    ab = root / AB[:2] / AB
    ab.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ab))
    conn.execute("CREATE TABLE ABPerson (ROWID INTEGER, First TEXT, Last TEXT, Middle TEXT, Organization TEXT, Department TEXT, Nickname TEXT, Note TEXT)")
    conn.execute("CREATE TABLE ABMultiValue (UID INTEGER, record_id INTEGER, property INTEGER, identifier INTEGER, label INTEGER, value TEXT)")
    conn.execute("CREATE TABLE ABMultiValueLabel (value TEXT)")
    conn.execute("INSERT INTO ABPerson VALUES (1, 'Ivan', 'Petrov', '', '', '', '', '')")
    conn.execute("INSERT INTO ABMultiValue VALUES (10, 1, 3, 0, 1, '+7 900 123-45-67')")
    conn.execute("INSERT INTO ABMultiValueLabel VALUES ('_$!<Mobile>!$_')")
    conn.commit(); conn.close()

    # Calendar.sqlitedb (real iOS 17+ schema)
    cal = root / CAL[:2] / CAL
    cal.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cal))
    conn.execute("CREATE TABLE CalendarItem (ROWID INTEGER, summary TEXT, location_id INTEGER, description TEXT, start_date REAL, end_date REAL, all_day INTEGER, calendar_id INTEGER)")
    conn.execute("INSERT INTO CalendarItem VALUES (1, 'Sync', NULL, NULL, 0, 3600, 0, NULL)")
    conn.commit(); conn.close()

    # Media files (sharded layout)
    _write_blob(root, PHOTO, b"fakejpeg")
    _write_blob(root, VIDEO, b"fakevideo")

    # Manifest.db (flat, in root)
    mdb = root / "Manifest.db"
    conn = sqlite3.connect(str(mdb))
    conn.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    conn.execute("INSERT INTO Files VALUES (?, 'HomeDomain', 'Library/AddressBook/AddressBook.sqlitedb', 1, NULL)", (AB,))
    conn.execute("INSERT INTO Files VALUES (?, 'HomeDomain', 'Library/Calendar/Calendar.sqlitedb', 1, NULL)", (CAL,))
    conn.execute("INSERT INTO Files VALUES (?, 'CameraRollDomain', '100APPLE/IMG_0001.JPG', 2, NULL)", (PHOTO,))
    conn.execute("INSERT INTO Files VALUES (?, 'CameraRollDomain', '100APPLE/IMG_0002.MOV', 2, NULL)", (VIDEO,))
    conn.commit(); conn.close()
    return root


class TestEngine(unittest.TestCase):
    def test_migrate_contacts_and_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = make_backup(Path(tmp) / "backup")
            dest = Path(tmp) / "out"
            engine = MigrationEngine(backup, dest)
            result = engine.run([DataType.CONTACTS, DataType.CALENDAR])
            self.assertTrue(result.ok)
            self.assertEqual(result.succeeded, 2)
            self.assertTrue((dest / "apk_assets" / "contacts.vcf").exists())
            self.assertTrue((dest / "apk_assets" / "calendar.ics").exists())

    def test_migrate_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = make_backup(Path(tmp) / "backup")
            dest = Path(tmp) / "out"
            engine = MigrationEngine(backup, dest)
            result = engine.run([DataType.PHOTOS])
            self.assertTrue(result.ok)
            photos = list((dest / "media" / "photos").glob("*"))
            # only the .JPG photo, not the .MOV video
            self.assertEqual(len(photos), 1)
            self.assertTrue(photos[0].name.endswith(".JPG"))

    def test_migrate_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = make_backup(Path(tmp) / "backup")
            dest = Path(tmp) / "out"
            engine = MigrationEngine(backup, dest)
            result = engine.run([DataType.VIDEOS])
            self.assertTrue(result.ok)
            videos = list((dest / "media" / "videos").glob("*"))
            # only the .MOV video, not the .JPG photo
            self.assertEqual(len(videos), 1)
            self.assertTrue(videos[0].name.endswith(".MOV"))

    def test_missing_type_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            # empty backup -> no AddressBook
            backup = Path(tmp) / "backup"
            (backup / "Manifest.db").parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(backup / "Manifest.db"))
            conn.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
            conn.commit(); conn.close()
            dest = Path(tmp) / "out"
            engine = MigrationEngine(backup, dest)
            result = engine.run([DataType.CONTACTS])
            self.assertFalse(result.ok)
            self.assertEqual(result.succeeded, 0)
            self.assertIn("not found", result.types[0].message)

    def test_progress_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = make_backup(Path(tmp) / "backup")
            dest = Path(tmp) / "out"
            events = []
            engine = MigrationEngine(backup, dest, progress_cb=lambda p, s, m: events.append((p, s)))
            engine.run([DataType.CONTACTS])
            self.assertTrue(any(s == "migrated" for _, s in events))


if __name__ == "__main__":
    unittest.main()
