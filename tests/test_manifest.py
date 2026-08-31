"""Unit tests for Manifest traversal."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.manifest import find_by_domain, find_by_path, list_files, resolve_blob


def make_backup(path: Path) -> Path:
    db = path / "Manifest.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)"
    )
    rows = [
        ("abc123", "HomeDomain", "Library/AddressBook/AddressBook.sqlitedb"),
        ("def456", "CameraRollDomain", "100APPLE/IMG_0001.HEIC"),
        ("ghi789", "CameraRollDomain", "100APPLE/IMG_0002.JPG"),
        ("jkl012", "HomeDomain", "Library/Calendar/Calendar.sqlitedb"),
    ]
    for i, (fid, dom, rel) in enumerate(rows):
        conn.execute(
            "INSERT INTO Files VALUES (?, ?, ?, ?, NULL)", (fid, dom, rel, i)
        )
    conn.commit()
    conn.close()
    return path


class TestManifest(unittest.TestCase):
    def test_list_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp))
            entries = list_files(root)
            self.assertEqual(len(entries), 4)

    def test_find_by_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp))
            media = find_by_domain(root, "CameraRollDomain")
            self.assertEqual(len(media), 2)
            self.assertTrue(all(e.domain.startswith("CameraRollDomain") for e in media))

    def test_find_by_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp))
            e = find_by_path(root, "Library/AddressBook/AddressBook.sqlitedb")
            self.assertIsNotNone(e)
            self.assertEqual(e.file_id, "abc123")
            self.assertEqual(e.domain, "HomeDomain")

    def test_find_by_path_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp))
            self.assertIsNone(find_by_path(root, "nope/missing.db"))

    def test_resolve_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp))
            e = find_by_path(root, "Library/AddressBook/AddressBook.sqlitedb")
            self.assertEqual(resolve_blob(root, e), root / "abc123")

    def test_missing_manifest(self):
        with self.assertRaises(FileNotFoundError):
            list_files("/nonexistent/backup")


if __name__ == "__main__":
    unittest.main()
