"""Core conversion logic: turn a raw contacts .txt dump into clean vCard (.vcf).

The input files look like a tab-separated export with the columns:

    <blank>  name  number  connected-via

Every contact is usually repeated once per source account
(com.android.local, com.google, com.whatsapp), so the same name+number
shows up several times. This module keeps only the (name, phone) pairs,
removes the duplicates and the extra columns, and builds a vCard file.

The parsing/vCard functions are kept free of any Telegram code so they can
be unit-tested on their own (see test_converter.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Contact:
    name: str
    phone: str


# A "phone" must contain at least one digit once cleaned. This drops the
# header row ("number") and any stray blank/garbage lines.
_DIGIT_RE = re.compile(r"\d")


def clean_phone(raw: str) -> str:
    """Normalise a phone string: keep a single leading '+' and the digits.

    Removes spaces, and trailing junk that appears in the exports such as
    'p' or ';' (e.g. '+919421414002p', '7387381517;', '+91 87660 66168').
    Returns '' if there is no digit at all.
    """
    raw = raw.strip()
    if not _DIGIT_RE.search(raw):
        return ""
    has_plus = raw.lstrip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    return ("+" if has_plus else "") + digits


def parse_contacts(text: str) -> list[Contact]:
    """Parse the raw export text into a de-duplicated list of contacts.

    Order of first appearance is preserved. Duplicates are collapsed on the
    (name, cleaned-phone) pair, so a person listed once per source account
    becomes a single entry, while the same name with two different numbers
    stays as two entries.
    """
    contacts: list[Contact] = []
    seen: set[tuple[str, str]] = set()

    for line in text.splitlines():
        # Split on tabs and drop empty cells (there's a leading blank column,
        # and the number field itself may contain spaces so we must NOT split
        # on general whitespace).
        parts = [p.strip() for p in line.split("\t")]
        parts = [p for p in parts if p]
        if len(parts) < 2:
            continue

        name, raw_number = parts[0], parts[1]

        # Skip the header row.
        if name.lower() == "name" and raw_number.lower() == "number":
            continue

        phone = clean_phone(raw_number)
        if not phone:
            continue

        name = name.strip()
        if not name:
            name = phone  # fall back to the number as the display name

        key = (name, phone)
        if key in seen:
            continue
        seen.add(key)
        contacts.append(Contact(name=name, phone=phone))

    return contacts


def _escape(value: str) -> str:
    """Escape special characters for a vCard 3.0 text value."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_vcf(contacts: list[Contact]) -> str:
    """Build a vCard 3.0 document (UTF-8 text) from the contacts."""
    cards: list[str] = []
    for c in contacts:
        name = _escape(c.name)
        cards.append(
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            f"N:{name};;;;\r\n"
            f"FN:{name}\r\n"
            f"TEL;TYPE=CELL:{c.phone}\r\n"
            "END:VCARD\r\n"
        )
    return "".join(cards)


def convert_text_to_vcf(text: str) -> tuple[str, int]:
    """Convenience wrapper: raw text -> (vcf string, number of contacts)."""
    contacts = parse_contacts(text)
    return build_vcf(contacts), len(contacts)
