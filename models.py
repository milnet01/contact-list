from __future__ import annotations

import re
import sqlite3

import phoneutil


def _escape_like(term: str) -> str:
    """Escape special LIKE characters."""
    return term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _build_contact_query(
    search: str | None = None,
    contact_type: str | None = None,
    letter: str | None = None,
) -> tuple[str, list[str | int]]:
    """Build WHERE clause for contact listing. Returns (query_fragment, params)."""
    query = 'SELECT id, type, name, email, phone, notes, created_at, updated_at FROM contacts'
    params: list[str | int] = []
    conditions: list[str] = []

    if search:
        escaped = _escape_like(search)
        term = f'%{escaped}%'
        conditions.append(
            "(name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\')"
        )
        params.extend([term, term, term])

    if contact_type in ('individual', 'company'):
        conditions.append('type = ?')
        params.append(contact_type)

    if letter == '#':
        conditions.append('first_letter(name) = ?')
        params.append('#')
    elif letter and len(letter) == 1 and letter.isascii() and letter.isalpha():
        conditions.append('first_letter(name) = ?')
        params.append(letter.upper())

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    return query, params


def list_contacts(
    db: sqlite3.Connection,
    page: int = 1,
    per_page: int = 50,
    search: str | None = None,
    contact_type: str | None = None,
    letter: str | None = None,
    sort: str = 'name',
    sort_dir: str = 'asc',
) -> tuple[list[sqlite3.Row], int]:
    # Clamp pagination at the data layer too, so the "max 200 per page" contract
    # holds for every caller (tests, future API), not just the web route.
    per_page = max(1, min(per_page, 200))
    page = max(1, page)

    query, params = _build_contact_query(search, contact_type, letter)

    count_query = f'SELECT COUNT(*) FROM ({query})'
    total: int = db.execute(count_query, params).fetchone()[0]

    # Clamp the requested page to the last populated page, so an over-range
    # ?page= returns the final page's rows rather than an empty result. Folding
    # this in lets the web route reuse the total we already computed here
    # instead of issuing a second COUNT (CL-0017).
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)

    allowed_sorts = {
        'name': 'name COLLATE NOCASE',
        'type': 'type',
        'created': 'created_at',
        'updated': 'updated_at',
    }
    order_col = allowed_sorts.get(sort, 'name COLLATE NOCASE')
    direction = 'DESC' if sort_dir == 'desc' else 'ASC'
    query += f' ORDER BY {order_col} {direction}'
    query += ' LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])

    contacts = db.execute(query, params).fetchall()
    return contacts, total


def get_type_counts(db: sqlite3.Connection) -> dict[str, int]:
    """Return a dict of contact type -> count for the stats badges."""
    rows = db.execute(
        'SELECT type, COUNT(*) AS cnt FROM contacts GROUP BY type'
    ).fetchall()
    return {row['type']: row['cnt'] for row in rows}


def get_letter_counts(db: sqlite3.Connection) -> dict[str, int]:
    """Return a dict of first-letter -> count for the alpha nav bar.

    Uses the SQLite first_letter() function (registered in db.py) so accented
    initials fold onto their base letter ('Élodie' -> 'E') and the buckets
    match the letter filter's grouping exactly (CL-0014).
    """
    rows = db.execute(
        'SELECT first_letter(name) AS letter, COUNT(*) AS cnt '
        'FROM contacts GROUP BY letter'
    ).fetchall()
    return {row['letter']: row['cnt'] for row in rows}


def export_contacts(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all contacts with all fields for CSV export."""
    return db.execute(
        'SELECT id, type, name, email, phone, notes, created_at, updated_at '
        'FROM contacts ORDER BY name COLLATE NOCASE'
    ).fetchall()


def find_duplicates(
    db: sqlite3.Connection,
    name: str,
    phone: str | None = None,
    region: str = 'ZA',
    exclude_id: int | None = None,
) -> list[str]:
    """Find duplicate contacts by name or phone. Returns list of warning messages."""
    warnings: list[str] = []
    id_filter = 'AND id != ?' if exclude_id is not None else ''
    base_params: list = [exclude_id] if exclude_id is not None else []

    rows = db.execute(
        f'SELECT id, name FROM contacts WHERE name = ? COLLATE NOCASE {id_filter}',
        [name, *base_params],
    ).fetchall()
    if rows:
        warnings.append(f'A contact named "{name}" already exists.')

    if phone:
        # Compare on the normalized E.164 form so the same number typed
        # differently ('+1 202-555-0123' vs '2025550123') is still caught
        # (CL-0013). SQLite has no phone-normalization function, so scan the
        # (few, single-user) phone-bearing rows and compare in Python. Fall
        # back to exact string match when a value can't be parsed.
        target = phoneutil.normalize_e164(phone, region)
        if target is not None:
            candidates = db.execute(
                f'SELECT name, phone FROM contacts '
                f'WHERE phone IS NOT NULL {id_filter}',
                base_params,
            ).fetchall()
            for c in candidates:
                if phoneutil.normalize_e164(c['phone'], region) == target:
                    warnings.append(f'Phone number already used by "{c["name"]}".')
                    break
        else:
            rows = db.execute(
                f'SELECT id, name FROM contacts WHERE phone = ? {id_filter}',
                [phone, *base_params],
            ).fetchall()
            if rows:
                warnings.append(f'Phone number already used by "{rows[0]["name"]}".')

    return warnings


def find_all_duplicates(
    db: sqlite3.Connection,
    region: str = 'ZA',
) -> dict[str, list[list[sqlite3.Row]]]:
    """Scan all contacts for duplicates by name, email, and phone.

    Returns a dict with keys 'name', 'email', 'phone'.  Each value is a list
    of groups, where each group is a list of Row objects sharing the same value.
    """
    result: dict[str, list[list[sqlite3.Row]]] = {'name': [], 'email': [], 'phone': []}

    # Duplicate names (case-insensitive)
    name_groups = db.execute(
        "SELECT name COLLATE NOCASE AS norm_name "
        "FROM contacts GROUP BY norm_name HAVING COUNT(*) > 1"
    ).fetchall()
    for row in name_groups:
        contacts = db.execute(
            "SELECT id, type, name, email, phone FROM contacts "
            "WHERE name = ? COLLATE NOCASE ORDER BY name",
            [row['norm_name']],
        ).fetchall()
        result['name'].append(contacts)

    # Duplicate emails (case-insensitive, skip NULLs)
    email_groups = db.execute(
        "SELECT LOWER(email) AS norm_email "
        "FROM contacts WHERE email IS NOT NULL AND email != '' "
        "GROUP BY norm_email HAVING COUNT(*) > 1"
    ).fetchall()
    for row in email_groups:
        contacts = db.execute(
            "SELECT id, type, name, email, phone FROM contacts "
            "WHERE LOWER(email) = ? ORDER BY name COLLATE NOCASE",
            [row['norm_email']],
        ).fetchall()
        result['email'].append(contacts)

    # Duplicate phones: bucket by the normalized E.164 form so the same number
    # typed differently ('+27 11 555 0001' vs '0115550001') groups together,
    # matching the on-create warning (find_duplicates, CL-0013/CL-0027). SQLite
    # has no phone-normalization function, so bucket the (few, single-user)
    # phone-bearing rows in Python; a value that can't be parsed falls back to
    # its exact string. Rows are pre-ordered by name so each group stays sorted.
    phone_rows = db.execute(
        "SELECT id, type, name, email, phone FROM contacts "
        "WHERE phone IS NOT NULL AND phone != '' ORDER BY name COLLATE NOCASE"
    ).fetchall()
    phone_buckets: dict[str, list[sqlite3.Row]] = {}
    for row in phone_rows:
        key = phoneutil.normalize_e164(row['phone'], region) or row['phone']
        phone_buckets.setdefault(key, []).append(row)
    result['phone'] = [group for group in phone_buckets.values() if len(group) > 1]

    return result


def get_contact(db: sqlite3.Connection, contact_id: int) -> sqlite3.Row | None:
    return db.execute(
        'SELECT * FROM contacts WHERE id = ?', [contact_id]
    ).fetchone()


def get_custom_fields(db: sqlite3.Connection, contact_id: int) -> list[sqlite3.Row]:
    return db.execute(
        'SELECT * FROM custom_fields WHERE contact_id = ? ORDER BY field_name COLLATE NOCASE',
        [contact_id],
    ).fetchall()


def _validate_custom_field_names(custom_fields: list[tuple[str, str]] | None) -> None:
    """Reject invalid or case-insensitively-duplicate custom field names before
    any DML, so the persistence layer enforces the contract for every caller
    (and so a colliding name can't trip the idx_cf_unique constraint mid-write)."""
    if not custom_fields:
        return
    seen: set[str] = set()
    for fn, _ in custom_fields:
        if not valid_field_name(fn):
            raise ValueError(f'Invalid custom field name: {fn!r}')
        key = fn.lower()
        if key in seen:
            raise ValueError(f'Duplicate custom field name: {fn!r}')
        seen.add(key)


VALID_CONTACT_TYPES = ('individual', 'company')


def _validate_contact_type(contact_type: str) -> None:
    """Fail fast on a bad type with a clear error, rather than letting the SQL
    CHECK constraint surface as a raw IntegrityError 500 (CL-0015)."""
    if contact_type not in VALID_CONTACT_TYPES:
        raise ValueError(f'Invalid contact type: {contact_type!r}')


def create_contact(
    db: sqlite3.Connection,
    contact_type: str,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    custom_fields: list[tuple[str, str]] | None = None,
) -> int:
    _validate_contact_type(contact_type)
    _validate_custom_field_names(custom_fields)

    # `with db` commits on success and rolls back on any error, so a failed
    # custom-field insert can't leave a half-applied write pending on the
    # connection for a later commit() to flush.
    with db:
        cursor = db.execute(
            'INSERT INTO contacts (type, name, email, phone, notes) VALUES (?, ?, ?, ?, ?)',
            [contact_type, name, email, phone, notes],
        )
        contact_id = cursor.lastrowid
        if custom_fields:
            db.executemany(
                'INSERT INTO custom_fields (contact_id, field_name, field_value) VALUES (?, ?, ?)',
                [(contact_id, fn, fv) for fn, fv in custom_fields],
            )
    return contact_id


def update_contact(
    db: sqlite3.Connection,
    contact_id: int,
    contact_type: str,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    custom_fields: list[tuple[str, str]] | None = None,
) -> None:
    # Validate before any mutation — update deletes the old custom fields below,
    # so a bad type or bad/duplicate name must fail before that delete.
    _validate_contact_type(contact_type)
    _validate_custom_field_names(custom_fields)

    # `with db` makes the UPDATE + DELETE + re-insert atomic: if the re-insert
    # fails, the delete of the old custom fields is rolled back too, so a failed
    # update can't silently wipe a contact's existing custom fields.
    with db:
        db.execute(
            """UPDATE contacts
               SET type=?, name=?, email=?, phone=?, notes=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
               WHERE id=?""",
            [contact_type, name, email, phone, notes, contact_id],
        )
        # Replace custom fields: delete all, re-insert
        db.execute('DELETE FROM custom_fields WHERE contact_id = ?', [contact_id])
        if custom_fields:
            db.executemany(
                'INSERT INTO custom_fields (contact_id, field_name, field_value) VALUES (?, ?, ?)',
                [(contact_id, fn, fv) for fn, fv in custom_fields],
            )


def delete_contact(db: sqlite3.Connection, contact_id: int) -> None:
    with db:
        db.execute('DELETE FROM contacts WHERE id = ?', [contact_id])


_FIELD_NAME_RE = re.compile(r'^[a-zA-Z0-9_ ]{1,64}$')


def valid_field_name(name: str) -> bool:
    return bool(_FIELD_NAME_RE.match(name))
