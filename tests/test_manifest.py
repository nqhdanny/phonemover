"""Unit tests for Manifest traversal."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.manifest import find_by_domain, find_by_path, list_files, resolve_blob


def make_backup(path: Path, sharded: bool = True) -> Path:
    """Build a synthetic backup. sharded=True mimics real iOS layout
    (blobs under <first-2-hex>/<fileID>); sharded=False uses flat layout."""
    path.mkdir(parents=True, exist_ok=True)
    db = path / "Manifest.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)"
    )
    # Use realistic 40-hex fileIDs so sharding logic is exercised.
    rows = [
        ("31bb7ba8914766d4ba40d6dfb6113c8b614be442", "HomeDomain", "Library/AddressBook/AddressBook.sqlitedb"),
        ("2041457d5fe04d39d0ab481178355df6781e6858", "HomeDomain", "Library/Calendar/Calendar.sqlitedb"),
        ("aa00000000000000000000000000000000000001", "CameraRollDomain", "100APPLE/IMG_0001.HEIC"),
        ("bb00000000000000000000000000000000000002", "CameraRollDomain", "100APPLE/IMG_0002.JPG"),
    ]
    for i, (fid, dom, rel) in enumerate(rows):
        conn.execute(
            "INSERT INTO Files VALUES (?, ?, ?, ?, NULL)", (fid, dom, rel, i)
        )
        # Create the physical blob.
        if sharded:
            blob = path / fid[:2] / fid
            blob.parent.mkdir(parents=True, exist_ok=True)
        else:
            blob = path / fid
        blob.write_bytes(b"dummy" + fid.encode())
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
            self.assertEqual(e.file_id, "31bb7ba8914766d4ba40d6dfb6113c8b614be442")
            self.assertEqual(e.domain, "HomeDomain")

    def test_find_by_path_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp))
            self.assertIsNone(find_by_path(root, "nope/missing.db"))

    def test_resolve_blob_sharded(self):
        """Real iOS layout: blob lives under <first-2-hex>/<fileID>."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp), sharded=True)
            e = find_by_path(root, "Library/AddressBook/AddressBook.sqlitedb")
            self.assertEqual(
                resolve_blob(root, e),
                root / "31" / "31bb7ba8914766d4ba40d6dfb6113c8b614be442",
            )
            self.assertTrue(resolve_blob(root, e).is_file())

    def test_resolve_blob_flat(self):
        """Legacy flat layout: blob directly under the backup root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_backup(Path(tmp), sharded=False)
            e = find_by_path(root, "Library/AddressBook/AddressBook.sqlitedb")
            self.assertEqual(
                resolve_blob(root, e),
                root / "31bb7ba8914766d4ba40d6dfb6113c8b614be442",
            )
            self.assertTrue(resolve_blob(root, e).is_file())

    def test_missing_manifest(self):
        with self.assertRaises(FileNotFoundError):
            list_files("/nonexistent/backup")


if __name__ == "__main__":
    unittest.main()
