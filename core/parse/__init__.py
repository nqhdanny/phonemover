"""Parsers — extract structured data from an iOS backup directory.

An iOS backup produced by pymobiledevice3/iTunes has:
  Manifest.db   (SQLite)  -> Files(fileID, domain, relativePath, ...)
  <fileID>               -> actual file contents (SHA1-named, in backup root)
"""

from .bookmarks import bookmarks_to_html, write_bookmarks
from .calendar import calendar_to_ics, write_ics
from .contacts import contacts_to_vcard
from .notes import notes_to_text, write_notes
from .photos import extract_photos, extract_videos
from .reminders import reminders_to_ics, write_reminders

__all__ = [
    "bookmarks_to_html",
    "write_bookmarks",
    "calendar_to_ics",
    "write_ics",
    "contacts_to_vcard",
    "extract_photos",
    "extract_videos",
    "notes_to_text",
    "write_notes",
    "reminders_to_ics",
    "write_reminders",
]
