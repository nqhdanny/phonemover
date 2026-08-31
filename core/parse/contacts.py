"""Contacts: read iOS AddressBook.sqlitedb -> vCard 3.0 text.

iOS address book schema (stable across iOS 10+):
  ABPerson(ROWID, First, Last, MiddleName, Organization, Department, ...)
  ABMultiValue(UID, record_id, property, identifier, label, value)
  ABMultiValueLabel(UID, label, value)

property codes: 3 = phone, 4 = email, 6 = url, 5 = date (simplified here).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

# property code -> vCard field
_PROPERTY_TO_VCARD = {3: "TEL", 4: "EMAIL", 6: "URL"}

# Common iOS label values already readable; unknown labels pass through.
_LABEL_VALUE_TO_TYPE = {
    "$!<Mobile>!$": "CELL",
    "$!<Home>!$": "HOME",
    "$!<Work>!$": "WORK",
    "$!<Other>!$": "OTHER",
    "home": "HOME",
    "work": "WORK",
}


def _read_multi_values(conn: sqlite3.Connection) -> dict[int, list[tuple[int, str, str]]]:
    """record_id -> list of (property, label_value, value)."""
    out: dict[int, list[tuple[int, str, str]]] = {}
    try:
        rows = conn.execute(
            "SELECT record_id, property, label, value FROM ABMultiValue ORDER BY record_id, identifier"
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for record_id, prop, label, value in rows:
        # resolve label code -> value via ABMultiValueLabel when possible
        label_val = label or ""
        if isinstance(label, int) or (isinstance(label, str) and label.isdigit()):
            try:
                lab = conn.execute(
                    "SELECT value FROM ABMultiValueLabel WHERE UID = ?", (int(label),)
                ).fetchone()
                if lab:
                    label_val = lab[0]
            except sqlite3.OperationalError:
                pass
        out.setdefault(record_id, []).append((int(prop), label_val, value or ""))
    return out


def _vcard_type(label: str) -> str:
    if not label:
        return "VOICE"
    if label.startswith("$!<") and label.endswith("!$"):
        inner = label[3:-3]
        return _LABEL_VALUE_TO_TYPE.get(label, inner.upper())
    return _LABEL_VALUE_TO_TYPE.get(label.lower(), "OTHER")


def contacts_to_vcard(db_path: str | Path) -> str:
    """Export all contacts as a single vCard 3.0 text blob."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Address book database not found: {db}")

    cards: list[str] = []
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            """
            SELECT ROWID, First, Last, MiddleName, Organization, Department, Nickname, Note
            FROM ABPerson
            """
        ).fetchall()
        multi = _read_multi_values(conn)

        for rowid, first, last, middle, org, dept, nick, note in rows:
            lines = ["BEGIN:VCARD", "VERSION:3.0"]
            full_name = " ".join(p for p in (first, middle, last) if p) or org or ""
            if full_name:
                lines.append(f"FN:{full_name}")
            if last:
                lines.append(f"N:{last};{first or ''};;;")
            if org:
                lines.append(f"ORG:{org}")
            if dept:
                lines.append(f"TITLE:{dept}")
            if nick:
                lines.append(f"NICKNAME:{nick}")
            if note:
                lines.append(f"NOTE:{note}")

            for prop, label, value in multi.get(rowid, []):
                if prop in _PROPERTY_TO_VCARD and value:
                    vtype = _vcard_type(label)
                    lines.append(f"{_PROPERTY_TO_VCARD[prop]};TYPE={vtype}:{value}")

            lines.append("END:VCARD")
            cards.append("\n".join(lines))
    return "\n".join(cards) + ("\n" if cards else "")


def write_vcards(db_path: str | Path, out_path: str | Path) -> int:
    """Export contacts and write to out_path. Returns contact count."""
    text = contacts_to_vcard(db_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text.count("BEGIN:VCARD")
