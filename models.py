from __future__ import annotations

import re
import sqlite3


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

    if letter and len(letter) == 1 and letter.isascii() and letter.isalpha():
        conditions.append("UPPER(SUBSTR(name, 1, 1)) = ?")
        params.append(letter.upper())
    elif letter == '#':
        conditions.append("SUBSTR(name, 1, 1) NOT GLOB '[A-Za-z]*'")

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    return query, params


def count_contacts(
    db: sqlite3.Connection,
    search: str | None = None,
    contact_type: str | None = None,
    letter: str | None = None,
) -> int:
    """Return the total number of contacts matching the given filters."""
    query, params = _build_contact_query(search, contact_type, letter)
    return db.execute(f'SELECT COUNT(*) FROM ({query})', params).fetchone()[0]


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
    """Return a dict of first-letter -> count for the alpha nav bar."""
    rows = db.execute(
        "SELECT UPPER(SUBSTR(name, 1, 1)) AS letter, COUNT(*) AS cnt "
        "FROM contacts GROUP BY letter ORDER BY letter"
    ).fetchall()
    counts: dict[str, int] = {}
    other = 0
    for row in rows:
        ltr = row['letter']
        # Only ASCII A-Z get their own bucket; SQLite's UPPER() (used by the
        # letter filter) folds only ASCII, so non-ASCII initials must fall into
        # the '#' bucket here too or the count and the filter would disagree
        # (bucket shows a count but clicking it returns nothing).
        if ltr and ltr.isascii() and ltr.isalpha():
            counts[ltr] = row['cnt']
        else:
            other += row['cnt']
    if other:
        counts['#'] = other
    return counts


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
        rows = db.execute(
            f'SELECT id, name FROM contacts WHERE phone = ? {id_filter}',
            [phone, *base_params],
        ).fetchall()
        if rows:
            existing = rows[0]['name']
            warnings.append(f'Phone number already used by "{existing}".')

    return warnings


def find_all_duplicates(
    db: sqlite3.Connection,
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

    # Duplicate phones (exact match, skip NULLs)
    phone_groups = db.execute(
        "SELECT phone FROM contacts WHERE phone IS NOT NULL AND phone != '' "
        "GROUP BY phone HAVING COUNT(*) > 1"
    ).fetchall()
    for row in phone_groups:
        contacts = db.execute(
            "SELECT id, type, name, email, phone FROM contacts "
            "WHERE phone = ? ORDER BY name COLLATE NOCASE",
            [row['phone']],
        ).fetchall()
        result['phone'].append(contacts)

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


def create_contact(
    db: sqlite3.Connection,
    contact_type: str,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    custom_fields: list[tuple[str, str]] | None = None,
) -> int:
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
    # so a bad/duplicate name must fail before that delete, not after.
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
