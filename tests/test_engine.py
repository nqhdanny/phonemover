"""Unit tests for the migration engine (synthetic backup, no device)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.engine import MigrationEngine
from core.models import DataType


def make_backup(root: Path) -> Path:
    """Build a minimal backup with AddressBook + Calendar + a media file."""
    root.mkdir(parents=True, exist_ok=True)

    # AddressBook.sqlitedb (blob: 'ABDB')
    ab = root / "ABDB"
    conn = sqlite3.connect(str(ab))
    conn.execute("CREATE TABLE ABPerson (ROWID INTEGER, First TEXT, Last TEXT, MiddleName TEXT, Organization TEXT, Department TEXT, Nickname TEXT, Note TEXT)")
    conn.execute("CREATE TABLE ABMultiValue (UID INTEGER, record_id INTEGER, property INTEGER, identifier INTEGER, label INTEGER, value TEXT)")
    conn.execute("CREATE TABLE ABMultiValueLabel (UID INTEGER, label TEXT, value TEXT)")
    conn.execute("INSERT INTO ABPerson VALUES (1, 'Ivan', 'Petrov', '', '', '', '', '')")
    conn.execute("INSERT INTO ABMultiValue VALUES (10, 1, 3, 0, 100, '+7 900 123-45-67')")
    conn.execute("INSERT INTO ABMultiValueLabel VALUES (100, 'mobile', '$!<Mobile>!$')")
    conn.commit(); conn.close()

    # Calendar.sqlitedb (blob: 'CALDB')
    cal = root / "CALDB"
    conn = sqlite3.connect(str(cal))
    conn.execute("CREATE TABLE CalendarItem (ROWID INTEGER, summary TEXT, location TEXT, start_date REAL, end_date REAL, all_day INTEGER, calendar_id INTEGER, notes TEXT)")
    conn.execute("INSERT INTO CalendarItem VALUES (1, 'Sync', NULL, 0, 3600, 0, NULL, NULL)")
    conn.commit(); conn.close()

    # Media files (blobs: 'MEDIA1' photo, 'MEDIA2' video)
    (root / "MEDIA1").write_bytes(b"fakejpeg")
    (root / "MEDIA2").write_bytes(b"fakevideo")

    # Manifest.db
    mdb = root / "Manifest.db"
    conn = sqlite3.connect(str(mdb))
    conn.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    conn.execute("INSERT INTO Files VALUES ('ABDB', 'HomeDomain', 'Library/AddressBook/AddressBook.sqlitedb', 1, NULL)")
    conn.execute("INSERT INTO Files VALUES ('CALDB', 'HomeDomain', 'Library/Calendar/Calendar.sqlitedb', 1, NULL)")
    conn.execute("INSERT INTO Files VALUES ('MEDIA1', 'CameraRollDomain', '100APPLE/IMG_0001.JPG', 2, NULL)")
    conn.execute("INSERT INTO Files VALUES ('MEDIA2', 'CameraRollDomain', '100APPLE/IMG_0002.MOV', 2, NULL)")
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
