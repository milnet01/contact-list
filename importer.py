"""Shared helpers for CSV and vCard import (CL-0022, CL-0023).

Kept separate from `models.py` (DB access) and `vcard.py` (vCard text) so the
one multi-value rule — first value is primary, extras become numbered custom
fields — lives in a single place both import paths call.
"""

from __future__ import annotations

import csv
import hashlib
import io

from models import sanitize_field_name

# Column-header aliases → mapping target, for the pre-filled guess on the
# mapping screen. Not exhaustive; the user can override every column.
_ALIASES = {
    'name': 'name', 'full name': 'name', 'display name': 'name',
    'first name': 'name', 'last name': 'name', 'given name': 'name',
    'family name': 'name', 'contact name': 'name',
    'type': 'type', 'category': 'type',
    'email': 'email', 'e-mail': 'email', 'email address': 'email',
    'e-mail address': 'email', 'email 1': 'email',
    'phone': 'phone', 'mobile': 'phone', 'tel': 'phone', 'telephone': 'phone',
    'phone 1': 'phone', 'phone number': 'phone', 'cell': 'phone',
    'notes': 'notes', 'note': 'notes',
}

TARGETS = ('name', 'type', 'email', 'phone', 'notes', 'custom', 'ignore')


def header_signature(headers: list[str]) -> str:
    """A stable signature of a CSV header layout: each header trimmed and
    lower-cased, joined in source order, hashed. Used to look up and store a
    remembered column mapping (CL-0022)."""
    norm = '\x1f'.join(h.strip().lower() for h in headers)
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()


def split_multivalue(kind: str, values: list[str]) -> tuple[str | None, list[tuple[str, str]]]:
    """Given a `kind` label ('Email' / 'Phone') and its values in order, return
    (primary, extras) where `primary` is the first non-empty value and `extras`
    is a list of (label, value) pairs numbered from 2 — e.g. ('Email 2', ...).
    The numbered labels are always valid `field_name`s."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return None, []
    extras = [(f'{kind} {i}', v) for i, v in enumerate(vals[1:], start=2)]
    return vals[0], extras


def parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse CSV text into (headers, data_rows). Rows are returned verbatim
    (possibly ragged); apply_mapping pads/truncates them against the header."""
    rows = [list(r) for r in csv.reader(io.StringIO(text))]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def guess_target(header: str) -> str:
    """Guess a mapping target for one column header (else 'ignore')."""
    return _ALIASES.get(header.strip().lower(), 'ignore')


def guess_mapping(headers: list[str]) -> dict[int, str]:
    """Column-index → guessed target for every header."""
    return {i: guess_target(h) for i, h in enumerate(headers)}


def _unique_label(base: str, used: set[str]) -> str:
    """Return `base`, or `base 2`/`base 3`/… so the result is unique
    (case-insensitive) within `used`; records the choice in `used`."""
    label = base
    n = 2
    while label.lower() in used:
        label = f'{base} {n}'
        n += 1
    used.add(label.lower())
    return label


def apply_mapping(
    headers: list[str],
    rows: list[list[str]],
    mapping: dict[int, str],
    default_type: str,
) -> tuple[list[tuple[dict, list[tuple[str, str]]]], int]:
    """Apply a column mapping to CSV rows. Returns (built, skipped) where each
    built entry is (fields, custom_fields) ready for models.import_contact, and
    skipped counts rows with no name and no email. Duplicate/extra values fold
    into numbered custom fields with row-unique labels (never a dup that would
    trip idx_cf_unique)."""
    n = len(headers)
    # Base custom-field label per custom-mapped column (sanitised header).
    base_labels: dict[int, str] = {}
    for i, target in mapping.items():
        if target == 'custom':
            base = sanitize_field_name(headers[i]) if i < n else ''
            base_labels[i] = base or f'Field {i + 1}'

    built: list[tuple[dict, list[tuple[str, str]]]] = []
    skipped = 0
    for row in rows:
        cells = (list(row) + [''] * n)[:n]
        names: list[str] = []
        emails: list[str] = []
        phones: list[str] = []
        notes_parts: list[str] = []
        type_val = ''
        raw_customs: list[tuple[str, str]] = []
        for i in sorted(mapping):
            target = mapping[i]
            val = cells[i].strip()
            if target == 'name':
                if val:
                    names.append(val)
            elif target == 'type':
                if val:
                    type_val = val
            elif target == 'email':
                emails.append(val)
            elif target == 'phone':
                phones.append(val)
            elif target == 'notes':
                if val:
                    notes_parts.append(val)
            elif target == 'custom' and val:
                raw_customs.append((base_labels[i], val))

        name = ' '.join(names).strip()
        email, email_extras = split_multivalue('Email', emails)
        phone, phone_extras = split_multivalue('Phone', phones)
        if not name and not email:
            skipped += 1
            continue

        used: set[str] = set()
        customs = [
            (_unique_label(label, used), val)
            for label, val in (raw_customs + email_extras + phone_extras)
        ]
        ctype = type_val if type_val in ('individual', 'company') else default_type
        fields = {
            'type': ctype,
            'name': name,
            'email': email,
            'phone': phone,
            'notes': '\n'.join(notes_parts) if notes_parts else None,
        }
        built.append((fields, customs))
    return built, skipped
