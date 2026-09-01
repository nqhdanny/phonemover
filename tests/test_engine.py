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
            # Photos are now grouped into an album subfolder (fallback "Camera").
            photos = list((dest / "media" / "photos").rglob("*"))
            photos = [p for p in photos if p.is_file()]
            # only the .JPG photo, not the .MOV video
            self.assertEqual(len(photos), 1)
            self.assertTrue(photos[0].name.endswith(".JPG"))
            self.assertEqual(photos[0].parent.name, "Camera")

    def test_migrate_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = make_backup(Path(tmp) / "backup")
            dest = Path(tmp) / "out"
            engine = MigrationEngine(backup, dest)
            result = engine.run([DataType.VIDEOS])
            self.assertTrue(result.ok)
            # Videos are grouped into a single "Video" subfolder.
            videos = list((dest / "media" / "videos").rglob("*"))
            videos = [v for v in videos if v.is_file()]
            # only the .MOV video, not the .JPG photo
            self.assertEqual(len(videos), 1)
            self.assertTrue(videos[0].name.endswith(".MOV"))
            self.assertEqual(videos[0].parent.name, "Video")

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

    def test_migrate_photos_preserves_albums(self):
        """A backup with Photos.sqlite must group photos by album name."""
        with tempfile.TemporaryDirectory() as tmp:
            backup = make_backup_with_albums(Path(tmp) / "backup")
            dest = Path(tmp) / "out"
            engine = MigrationEngine(backup, dest)
            result = engine.run([DataType.PHOTOS])
            self.assertTrue(result.ok)
            photos_dir = dest / "media" / "photos"
            # Two albums: "Camera" (camera roll) and "WhatsApp" (user album).
            self.assertTrue((photos_dir / "Camera").is_dir())
            self.assertTrue((photos_dir / "WhatsApp").is_dir())
            camera_files = [p.name for p in (photos_dir / "Camera").iterdir()]
            whatsapp_files = [p.name for p in (photos_dir / "WhatsApp").iterdir()]
            self.assertIn("IMG_0001.JPG", camera_files)
            self.assertIn("WA_0001.JPG", whatsapp_files)

            # date_taken is parsed from ZDATECREATED (CoreData 2001 epoch) so the
            # writer can stamp EXIF DateTimeOriginal into converted JPEGs.
            from core.parse.albums import build_album_map
            amap = build_album_map(backup)
            all_assets = [a for assets in amap.values() for a in assets]
            by_name = {a.filename: a for a in all_assets}
            self.assertEqual(by_name["IMG_0001.JPG"].date_taken, 700000000 + 978307200)
            self.assertEqual(by_name["WA_0001.JPG"].date_taken, 710000000 + 978307200)


def make_backup_with_albums(root: Path) -> Path:
    """Build a synthetic backup that includes a Photos.sqlite album mapping."""
    root.mkdir(parents=True, exist_ok=True)

    PHOTO1 = "cc00000000000000000000000000000000000001"  # camera roll
    PHOTO2 = "cc00000000000000000000000000000000000002"  # WhatsApp album
    PHOTOS_DB = "cc00000000000000000000000000000000000099"

    _write_blob(root, PHOTO1, b"fakejpeg1")
    _write_blob(root, PHOTO2, b"fakejpeg2")

    # Photos.sqlite with ZGENERICALBUM + ZASSET + Z_33ASSETS.
    photos_db = root / PHOTOS_DB[:2] / PHOTOS_DB
    photos_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(photos_db))
    conn.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE VARCHAR, ZKIND INTEGER)")
    conn.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY VARCHAR, ZFILENAME VARCHAR, ZDATECREATED REAL)")
    conn.execute("CREATE TABLE Z_33ASSETS (Z_33ALBUMS INTEGER, Z_3ASSETS INTEGER)")
    # WhatsApp album (ZKIND=2)
    conn.execute("INSERT INTO ZGENERICALBUM VALUES (50, 'WhatsApp', 2)")
    # Two assets: camera roll + WhatsApp
    conn.execute("INSERT INTO ZASSET VALUES (1, 'DCIM/100APPLE', 'IMG_0001.JPG', 700000000)")
    conn.execute("INSERT INTO ZASSET VALUES (2, 'PhotoData/CPLAssets/group1', 'WA_0001.JPG', 710000000)")
    # Link asset 2 -> WhatsApp album
    conn.execute("INSERT INTO Z_33ASSETS VALUES (50, 2)")
    conn.commit(); conn.close()

    # Manifest.db maps both photos + Photos.sqlite.
    mdb = root / "Manifest.db"
    conn = sqlite3.connect(str(mdb))
    conn.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    conn.execute("INSERT INTO Files VALUES (?, 'CameraRollDomain', 'Media/DCIM/100APPLE/IMG_0001.JPG', 1, NULL)", (PHOTO1,))
    conn.execute("INSERT INTO Files VALUES (?, 'CameraRollDomain', 'Media/PhotoData/CPLAssets/group1/WA_0001.JPG', 1, NULL)", (PHOTO2,))
    conn.execute("INSERT INTO Files VALUES (?, 'CameraRollDomain', 'Media/PhotoData/Photos.sqlite', 1, NULL)", (PHOTOS_DB,))
    conn.commit(); conn.close()
    return root


if __name__ == "__main__":
    unittest.main()
