"""Unit tests for the backup module (no device needed)."""

import tempfile
import unittest
from pathlib import Path

from core.backup import _find_backup_root


class TestBackup(unittest.TestCase):
    def test_find_backup_root_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backup"
            root.mkdir()
            (root / "Manifest.db").write_text("x")
            self.assertEqual(_find_backup_root(root), root)

    def test_find_backup_root_nested_udid(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "backup"
            udid_dir = parent / "00008140-ABCDEF"
            udid_dir.mkdir(parents=True)
            (udid_dir / "Manifest.db").write_text("x")
            self.assertEqual(_find_backup_root(parent), udid_dir)

    def test_find_backup_root_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            self.assertIsNone(_find_backup_root(empty))


if __name__ == "__main__":
    unittest.main()
