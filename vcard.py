"""Minimal hand-rolled vCard 3.0/4.0 parser and emitter (CL-0023).

Our contact record is small (one name, one email, one phone, plus custom
fields), and vCard is a line-based text format, so a dedicated library would be
more surface area than value. Export writes vCard 3.0; import reads 3.0 and 4.0.
Custom fields round-trip losslessly via `X-CL;X-LABEL=<name>:<value>` because
custom-field names are already constrained to a param-safe character set.
"""

from __future__ import annotations

from importer import split_multivalue


def _escape(value: str) -> str:
    """Escape a property value per RFC 6350/2426 (backslash first)."""
    return (
        value.replace('\\', '\\\\')
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


def emit(contacts: list[dict]) -> str:
    """Serialise contacts to one vCard 3.0 document. Each contact is a dict with
    keys type, name, email, phone, notes, custom_fields (list of (name, value))."""
    lines: list[str] = []
    for c in contacts:
        name = c['name']
        lines.append('BEGIN:VCARD')
        lines.append('VERSION:3.0')
        lines.append(f'FN:{_escape(name)}')
        if c.get('type') == 'company':
            lines.append(f'ORG:{_escape(name)}')
        else:
            lines.append(f'N:{_escape(name)};;;;')
        if c.get('email'):
            lines.append(f'EMAIL:{_escape(c["email"])}')
        if c.get('phone'):
            lines.append(f'TEL:{_escape(c["phone"])}')
        if c.get('notes'):
            lines.append(f'NOTE:{_escape(c["notes"])}')
        for fn, fv in c.get('custom_fields', []):
            # Field names are already [A-Za-z0-9_ ] — all vCard param SAFE-CHARs
            # — so X-LABEL needs no quoting/escaping.
            lines.append(f'X-CL;X-LABEL={fn}:{_escape(fv)}')
        lines.append('END:VCARD')
    return '\r\n'.join(lines) + '\r\n'


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
    custom = list(card['custom']) + email_extras + phone_extras

    return {
        'type': 'company' if is_company else 'individual',
        'name': name.strip(),
        'email': email,
        'phone': phone,
        'notes': card['notes'],
        'custom_fields': custom,
    }


def parse(text: str) -> list[dict]:
    """Parse a vCard 3.0/4.0 document into contact dicts. Cards with no usable
    name are skipped."""
    normalised = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    # Unfold: a line starting with space/tab continues the previous line.
    lines: list[str] = []
    for raw in normalised:
        if raw[:1] in (' ', '\t') and lines:
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
                'org': None, 'kind': None, 'notes': None,
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
        prop = segments[0].upper()
        params = segments[1:]

        if prop == 'FN':
            card['fn'] = _unescape(value)
        elif prop == 'N':
            card['n_raw'] = value
            parts = [_unescape(p) for p in _split_structured(value)]
            card['n_family'] = parts[0] if len(parts) > 0 else ''
            card['n_given'] = parts[1] if len(parts) > 1 else ''
        elif prop == 'ORG':
            card['org'] = _unescape(value)
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
