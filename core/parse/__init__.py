"""Parsers — extract structured data from an iOS backup directory.

An iOS backup produced by pymobiledevice3/iTunes has:
  Manifest.db   (SQLite)  -> Files(fileID, domain, relativePath, ...)
  <fileID>               -> actual file contents (SHA1-named, in backup root)
"""

from .calendar import calendar_to_ics, write_ics
from .contacts import contacts_to_vcard
from .photos import extract_photos

__all__ = [
    "calendar_to_ics",
    "write_ics",
    "contacts_to_vcard",
    "extract_photos",
]
