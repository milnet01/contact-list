"""Minimal hand-rolled vCard 3.0/4.0 parser and emitter (CL-0023).

Our contact record is small (one name, one email, one phone, plus custom
fields), and vCard is a line-based text format, so a dedicated library would be
more surface area than value. Export writes vCard 3.0; import reads 3.0 and 4.0,
plus vCard 2.1's quoted-printable values (CL-0075). The birthday, address and
organization custom fields travel as the standard BDAY, ADR and ORG so other
apps read them; every other custom field round-trips via
`X-CL;X-LABEL=<name>:<value>`. Custom-field names are constrained to a
param-safe character set, so X-LABEL needs no quoting.
"""

from __future__ import annotations

import quopri
import re
from collections.abc import Iterable, Iterator

from importer import split_multivalue
from models import _BIRTHDAY_RE, valid_field_name

# The custom fields that travel as standard properties (CL-0075): the same three
# Google sync maps (DESIGN §8.2), matched by name case-insensitively.
_STANDARD_FIELDS = {'birthday': 'BDAY', 'address': 'ADR', 'organization': 'ORG'}
_FOLD_OCTETS = 75  # RFC 6350 §3.2
# BDAY forms read on import: YYYY-MM-DD, YYYYMMDD, --MM-DD, --MMDD.
_BDAY_IN_RE = re.compile(r'(\d{4})-?(\d{2})-?(\d{2})|--(\d{2})-?(\d{2})')


def _escape(value: str) -> str:
    """Escape a property value per RFC 6350/2426 (backslash first).

    Carriage returns are folded into newlines BEFORE the newline escape, so
    every line break leaves as a literal ``\\n``. A bare CR would otherwise be
    emitted raw and act as a line terminator in the serialised card, which cost
    two things: a browser normalises a <textarea> to CRLF, so every multi-line
    note lost everything after its first line on a round-trip (INV-2 of
    2026-07-01-import-export-merge-design); and a CR inside imported data could
    inject whole fabricated cards into an exported file.
    """
    return (
        value.replace('\\', '\\\\')
        .replace('\r\n', '\n')
        .replace('\r', '\n')
        .replace('\n', '\\n')
        .replace(',', '\\,')
        .replace(';', '\\;')
    )


def _unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == '\\' and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({'n': '\n', 'N': '\n', ',': ',', ';': ';', '\\': '\\'}.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _split_structured(value: str) -> list[str]:
    """Split a structured value on unescaped ';' (for the N property)."""
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == '\\' and i + 1 < len(value):
            buf.append(value[i:i + 2])
            i += 2
        elif c == ';':
            parts.append(''.join(buf))
            buf = []
            i += 1
        else:
            buf.append(c)
            i += 1
    parts.append(''.join(buf))
    return parts


def emit(contacts: Iterable[dict]) -> str:
    """Serialise contacts to one vCard 3.0 document. Each contact is a dict with
    keys type, name, email, phone, notes, custom_fields (list of (name, value))."""
    return ''.join(iter_emit(contacts))


def _fold(line: str) -> str:
    """Fold a content line to at most 75 octets per physical line (RFC 6350
    §3.2): CRLF plus one space before each continuation, never splitting a
    multi-byte UTF-8 character."""
    if len(line.encode('utf-8')) <= _FOLD_OCTETS:
        return line
    pieces: list[str] = []
    buf = ''
    size = 0
    limit = _FOLD_OCTETS
    for ch in line:
        width = len(ch.encode('utf-8'))
        if size + width > limit:
            pieces.append(buf)
            buf, size = '', 0
            limit = _FOLD_OCTETS - 1  # the leading space counts
        buf += ch
        size += width
    pieces.append(buf)
    return '\r\n '.join(pieces)


def _standard_property(name: str, value: str, contact_type: str | None) -> str | None:
    """The BDAY/ADR/ORG line for a custom field, or None when it stays X-CL."""
    prop = _STANDARD_FIELDS.get(name.lower())
    if prop == 'BDAY':
        match = _BIRTHDAY_RE.fullmatch(value)
        if not match:
            return None
        year, month, day = match.groups()
        date = f'{year}-{month}-{day}' if year else f'--{month}-{day}'
        return f'BDAY;X-LABEL={name}:{date}'
    if prop == 'ADR':
        return f'ADR;X-LABEL={name}:;;{_escape(value)};;;;'
    if prop == 'ORG' and contact_type != 'company':
        # A company's ORG is its own name, so its organization field stays X-CL.
        return f'ORG;X-LABEL={name}:{_escape(value)}'
    return None


def iter_emit(contacts: Iterable[dict]) -> Iterator[str]:
    """Yield one serialised vCard per contact, CRLF-terminated, so an export can
    stream card by card (CL-0067). ``emit`` is these cards joined."""
    for c in contacts:
        name = c['name']
        lines = ['BEGIN:VCARD', 'VERSION:3.0', f'FN:{_escape(name)}']
        if c.get('type') == 'company':
            # RFC 2426 makes N required in 3.0; empty parts keep it a company.
            lines.append('N:;;;;')
            lines.append(f'ORG:{_escape(name)}')
        else:
            # Family name is the last word, given the rest: other apps sort and
            # display by N, while our own import reads FN first (CL-0093).
            *given, family = name.split() or ['']
            if not given:
                given, family = [family], ''
            lines.append(f'N:{_escape(family)};{_escape(" ".join(given))};;;')
        if c.get('email'):
            lines.append(f'EMAIL:{_escape(c["email"])}')
        if c.get('phone'):
            lines.append(f'TEL:{_escape(c["phone"])}')
        if c.get('notes'):
            lines.append(f'NOTE:{_escape(c["notes"])}')
        for fn, fv in c.get('custom_fields', []):
            # Field names are already [A-Za-z0-9_ ] — all vCard param SAFE-CHARs
            # — so X-LABEL needs no quoting/escaping.
            lines.append(
                _standard_property(fn, fv, c.get('type'))
                or f'X-CL;X-LABEL={fn}:{_escape(fv)}'
            )
        lines.append('END:VCARD')
        yield ''.join(_fold(line) + '\r\n' for line in lines)


def _finalize(card: dict) -> dict | None:
    """Turn accumulated properties into a contact dict, or None to skip."""
    name = card['fn']
    if not name and card['n_raw'] is not None:
        parts = [_unescape(p) for p in _split_structured(card['n_raw'])]
        family = parts[0] if len(parts) > 0 else ''
        given = parts[1] if len(parts) > 1 else ''
        name = ' '.join(x for x in (given, family) if x).strip()
    if not name or not name.strip():
        return None

    has_personal_name = bool(card['n_given'] or card['n_family'])
    is_company = card['kind'] == 'org' or (card['org'] and not has_personal_name)

    email, email_extras = split_multivalue('Email', card['emails'])
    phone, phone_extras = split_multivalue('Phone', card['phones'])

    standard: list[tuple[str, str]] = []
    if card['bday'] is not None:
        standard.append((card['bday'][0], _normalise_bday(card['bday'][1])))
    if card['adr'] is not None:
        parts = [_unescape(p).strip() for p in _split_structured(card['adr'][1])]
        address = ', '.join(p for p in parts if p)
        if address:
            standard.append((card['adr'][0], address))
    if card['org'] and card['org_label'] and not is_company:
        standard.append((card['org_label'], card['org']))
    # A standard property beats an X-CL of the same name, compared as
    # idx_cf_unique compares them, so the pair cannot collide on insert.
    taken = {n.lower() for n, _ in standard}
    private = [(n, v) for n, v in card['custom'] if n.lower() not in taken]
    custom = standard + private + email_extras + phone_extras

    return {
        'type': 'company' if is_company else 'individual',
        'name': name.strip(),
        'email': email,
        'phone': phone,
        'notes': card['notes'],
        'custom_fields': custom,
    }


def _normalise_bday(raw: str) -> str:
    """A BDAY value in the app's stored form (YYYY-MM-DD or MM-DD), or the raw
    text when it is not a date form this reads. A trailing time is dropped."""
    value = raw.strip().split('T', 1)[0]
    match = _BDAY_IN_RE.fullmatch(value)
    if not match:
        return raw.strip()
    year, month, day, ymonth, yday = match.groups()
    return f'{year}-{month}-{day}' if year else f'{ymonth}-{yday}'


def _param_value(params: list[str], key: str) -> str | None:
    for p in params:
        if p.upper().startswith(key + '='):
            return p[len(key) + 1:]
    return None


def _is_quoted_printable(params: list[str]) -> bool:
    # 3.0 spells it ENCODING=QUOTED-PRINTABLE; 2.1 allows the bare token.
    return any(p.upper() in ('ENCODING=QUOTED-PRINTABLE', 'QUOTED-PRINTABLE') for p in params)


def _head_params(line: str) -> list[str]:
    return line.split(':', 1)[0].split(';')[1:] if ':' in line else []


def _decode_quoted_printable(value: str, params: list[str]) -> str:
    raw = quopri.decodestring(value.encode('utf-8'))
    charset = _param_value(params, 'CHARSET') or 'utf-8'
    try:
        return raw.decode(charset, errors='replace')
    except LookupError:  # a charset name Python does not know
        return raw.decode('utf-8', errors='replace')


def _label(params: list[str], default: str) -> str:
    """The X-LABEL param's name when it is a valid field name, else ``default``
    -- a label from another app is not trusted to pass validation (INV-4)."""
    label = _param_value(params, 'X-LABEL')
    return label if label and valid_field_name(label) else default


def parse(text: str) -> list[dict]:
    """Parse a vCard 3.0/4.0 document into contact dicts. Cards with no usable
    name are skipped."""
    normalised = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    # Unfold: a line starting with space/tab continues the previous line, and
    # a quoted-printable line ending in '=' (a soft break) continues onto the
    # next line, which has no leading space.
    lines: list[str] = []
    for raw in normalised:
        if lines and lines[-1].endswith('=') and _is_quoted_printable(_head_params(lines[-1])):
            lines[-1] = lines[-1][:-1] + raw
        elif raw[:1] in (' ', '\t') and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    cards: list[dict] = []
    card: dict | None = None
    for line in lines:
        if not line.strip():
            continue
        upper = line.upper()
        if upper.startswith('BEGIN:VCARD'):
            card = {
                'fn': None, 'n_raw': None, 'n_given': '', 'n_family': '',
                'org': None, 'org_label': None, 'kind': None, 'notes': None,
                'bday': None, 'adr': None,
                'emails': [], 'phones': [], 'custom': [],
            }
            continue
        if upper.startswith('END:VCARD'):
            if card is not None:
                finalised = _finalize(card)
                if finalised is not None:
                    cards.append(finalised)
            card = None
            continue
        if card is None or ':' not in line:
            continue

        head, value = line.split(':', 1)
        segments = head.split(';')
        # RFC 6350 §3.3 allows a group prefix on a content line:
        # [group "."] name *(";" param) ":" value. Google Contacts and Apple
        # both emit grouped properties for custom-labelled entries
        # (item1.EMAIL;TYPE=INTERNET:..., item2.TEL:...). Without the strip,
        # "ITEM1.EMAIL" matched no branch below and the property was dropped
        # silently -- losing exactly the emails and phones that carried a
        # custom label from a real phone or Google export.
        prop = segments[0].rsplit('.', 1)[-1].upper()
        params = segments[1:]
        if _is_quoted_printable(params):
            value = _decode_quoted_printable(value, params)

        if prop == 'FN':
            card['fn'] = _unescape(value)
        elif prop == 'N':
            card['n_raw'] = value
            parts = [_unescape(p) for p in _split_structured(value)]
            card['n_family'] = parts[0] if len(parts) > 0 else ''
            card['n_given'] = parts[1] if len(parts) > 1 else ''
        elif prop == 'ORG':
            if card['org'] is None:
                card['org'] = _unescape(value)
                card['org_label'] = _label(params, 'organization')
        elif prop == 'BDAY':
            if card['bday'] is None:
                card['bday'] = (_label(params, 'birthday'), _unescape(value))
        elif prop == 'ADR':
            if card['adr'] is None:
                card['adr'] = (_label(params, 'address'), value)
        elif prop == 'KIND':
            card['kind'] = _unescape(value).strip().lower()
        elif prop == 'EMAIL':
            card['emails'].append(_unescape(value))
        elif prop == 'TEL':
            card['phones'].append(_unescape(value))
        elif prop == 'NOTE':
            card['notes'] = _unescape(value)
        elif prop == 'X-CL':
            label = None
            for p in params:
                if p.upper().startswith('X-LABEL='):
                    label = p[len('X-LABEL='):]
            if label:
                card['custom'].append((label, _unescape(value)))

    return cards
