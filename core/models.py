"""Data type definitions for PhoneMover.

v1.0 supports 5 core types (P0); more types will be enabled in v1.1+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DataType(str, Enum):
    """All migratable data types (P0 = v1.0, P1 = v1.1+)."""

    CONTACTS = "contacts"          # P0
    PHOTOS = "photos"              # P0
    VIDEOS = "videos"              # P0
    MUSIC = "music"                # P0
    CALENDAR = "calendar"          # P0
    MESSAGES = "messages"          # P1
    CALL_LOG = "call_log"          # P1
    NOTES = "notes"                # P1
    VOICE_MEMOS = "voice_memos"    # P1
    BOOKMARKS = "bookmarks"        # P1
    REMINDERS = "reminders"        # P2


@dataclass(frozen=True)
class DataTypeInfo:
    """Metadata about a data type (UI + core)."""

    key: DataType
    # UI labels are fetched via i18n; these keys map to translation strings.
    label_key: str
    priority: str  # "P0" / "P1" / "P2"
    enabled_in_v1: bool
    write_channel: str  # "mtp" | "apk" | "file"
    backup_domain: str = ""
    description: str = ""


# Registry of all data types with their properties.
DATA_TYPES: dict[DataType, DataTypeInfo] = {
    DataType.CONTACTS: DataTypeInfo(
        DataType.CONTACTS, "datatype.contacts", "P0", True, "apk",
        "HomeDomain/Library/AddressBook/AddressBook.sqlitedb",
    ),
    DataType.PHOTOS: DataTypeInfo(
        DataType.PHOTOS, "datatype.photos", "P0", True, "mtp",
        "Media/DCIM",
    ),
    DataType.VIDEOS: DataTypeInfo(
        DataType.VIDEOS, "datatype.videos", "P0", True, "mtp",
        "Media/DCIM",
    ),
    DataType.MUSIC: DataTypeInfo(
        DataType.MUSIC, "datatype.music", "P0", True, "mtp",
        "Media/iTunes_Control/Music",
    ),
    DataType.CALENDAR: DataTypeInfo(
        DataType.CALENDAR, "datatype.calendar", "P0", True, "apk",
        "HomeDomain/Library/Calendar/Calendar.sqlitedb",
    ),
    DataType.MESSAGES: DataTypeInfo(
        DataType.MESSAGES, "datatype.messages", "P1", False, "apk",
        "HomeDomain/Library/SMS/sms.db",
    ),
    DataType.CALL_LOG: DataTypeInfo(
        DataType.CALL_LOG, "datatype.call_log", "P1", False, "apk",
        "HomeDomain/Library/CallHistoryDB/CallHistory.storedata",
    ),
    DataType.NOTES: DataTypeInfo(
        DataType.NOTES, "datatype.notes", "P1", False, "apk",
        "HomeDomain/Library/Notes/NoteStore.sqlite",
    ),
    DataType.VOICE_MEMOS: DataTypeInfo(
        DataType.VOICE_MEMOS, "datatype.voice_memos", "P1", False, "mtp",
        "Media/Recordings",
    ),
    DataType.BOOKMARKS: DataTypeInfo(
        DataType.BOOKMARKS, "datatype.bookmarks", "P1", False, "file",
        "HomeDomain/Library/Safari/Bookmarks.db",
    ),
    DataType.REMINDERS: DataTypeInfo(
        DataType.REMINDERS, "datatype.reminders", "P2", False, "apk",
        "HomeDomain/Library/Reminders/Reminders.sqlitedb",
    ),
}


def v1_data_types() -> list[DataType]:
    """Data types enabled in v1.0."""
    return [t for t, info in DATA_TYPES.items() if info.enabled_in_v1]
