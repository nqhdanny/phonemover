"""Unit tests for core parsers (no real device needed)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.parse.contacts import contacts_to_vcard


def make_addressbook(path: Path) -> Path:
    """Build an address book matching the real iOS 17+ schema."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ABPerson (ROWID INTEGER, First TEXT, Last TEXT, Middle TEXT, Organization TEXT, Department TEXT, Nickname TEXT, Note TEXT)")
    conn.execute("CREATE TABLE ABMultiValue (UID INTEGER, record_id INTEGER, property INTEGER, identifier INTEGER, label INTEGER, value TEXT)")
    # Real schema: single TEXT column, label is a 1-based rowid index.
    conn.execute("CREATE TABLE ABMultiValueLabel (value TEXT)")
    conn.execute(
        "INSERT INTO ABPerson VALUES (1, 'Ivan', 'Petrov', '', 'ACME', 'Engineer', 'iva', 'test note')"
    )
    conn.execute("INSERT INTO ABMultiValue VALUES (10, 1, 3, 0, 1, '+7 900 123-45-67')")
    conn.execute("INSERT INTO ABMultiValue VALUES (11, 1, 4, 0, 2, 'ivan@example.com')")
    conn.execute("INSERT INTO ABMultiValueLabel VALUES ('_$!<Mobile>!$_')")
    conn.execute("INSERT INTO ABMultiValueLabel VALUES ('_$!<Home>!$_')")
    conn.commit()
    conn.close()
    return path


class TestContacts(unittest.TestCase):
    def test_vcard_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_addressbook(Path(tmp) / "AddressBook.sqlitedb")
            text = contacts_to_vcard(db)
            self.assertIn("BEGIN:VCARD", text)
            self.assertIn("FN:Ivan Petrov", text)
            self.assertIn("N:Petrov;Ivan;;;", text)
            self.assertIn("TEL;TYPE=CELL:+7 900 123-45-67", text)
            self.assertIn("EMAIL;TYPE=HOME:ivan@example.com", text)
            self.assertIn("ORG:ACME", text)
            self.assertIn("TITLE:Engineer", text)
            self.assertIn("NOTE:test note", text)

    def test_missing_db_raises(self):
        with self.assertRaises(FileNotFoundError):
            contacts_to_vcard("/nonexistent/AddressBook.sqlitedb")


if __name__ == "__main__":
    unittest.main()
