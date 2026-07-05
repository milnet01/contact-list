from __future__ import annotations

import datetime
import json
import re
import sqlite3

import phoneutil

# CL-0037: tag caps. MAX_TAG_LEN bounds a single tag's length; MAX_TAGS bounds
# how many tags one contact may carry (matching the hard-coded 50-item
# custom-field limit in routes.contacts). Both are enforced in _normalize_tags,
# which is the single choke-point for every tag write.
MAX_TAG_LEN = 50
MAX_TAGS = 50


def _escape_like(term: str) -> str:
    """Escape special LIKE characters."""
    return term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _build_contact_query(
    search: str | None = None,
    contact_type: str | None = None,
    letter: str | None = None,
    tags: list[str] | None = None,
) -> tuple[str, list[str | int]]:
    """Build WHERE clause for contact listing. Returns (query_fragment, params)."""
    # has_photo is a scalar EXISTS column spliced into the static SELECT prefix,
    # not a JOIN — a JOIN would fan out rows and inflate the COUNT(*)-over-subquery
    # total (the same constraint as CL-0025). No bound param, no effect on ordering.
    query = (
        'SELECT id, type, name, email, phone, notes, created_at, updated_at, '
        'EXISTS (SELECT 1 FROM contact_photos p WHERE p.contact_id = contacts.id) '
        'AS has_photo, '
        '(SELECT edited_at FROM contact_edits e WHERE e.contact_id = contacts.id) '
        'AS edited_at, '
        'EXISTS (SELECT 1 FROM contact_favourites f WHERE f.contact_id = contacts.id) '
        'AS is_favourite FROM contacts'
    )
    params: list[str | int] = []
    conditions: list[str] = []

    if search:
        escaped = _escape_like(search)
        term = f'%{escaped}%'
        # Search the core columns plus notes, and fall through to custom field
        # values via a subquery (CL-0025). We match field *values*, not field
        # *names* — merges create fields literally named "Phone 2"/"Email 2",
        # so matching names would make "phone" hit every merged contact.
        conditions.append(
            "(name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' "
            "OR phone LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\' "
            "OR id IN (SELECT contact_id FROM custom_fields "
            "WHERE field_value LIKE ? ESCAPE '\\'))"
        )
        params.extend([term, term, term, term, term])

    if contact_type in ('individual', 'company'):
        conditions.append('type = ?')
        params.append(contact_type)

    if letter == '#':
        conditions.append('first_letter(name) = ?')
        params.append('#')
    elif letter and len(letter) == 1 and letter.isascii() and letter.isalpha():
        conditions.append('first_letter(name) = ?')
        params.append(letter.upper())

    # CL-0037: AND-filter by tag. One scalar `id IN (subquery)` membership test
    # per selected tag — reuses the custom-field-search idiom above, so a contact
    # is returned at most once (no JOIN fan-out) and must carry ALL N tags.
    for tag in (tags or []):
        conditions.append(
            'id IN (SELECT ct.contact_id FROM contact_tags ct '
            'JOIN tags t ON t.id = ct.tag_id WHERE t.name = ? COLLATE NOCASE)'
        )
        params.append(tag)

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
    tags: list[str] | None = None,
) -> tuple[list[sqlite3.Row], int]:
    # Clamp pagination at the data layer too, so the "max 200 per page" contract
    # holds for every caller (tests, future API), not just the web route.
    per_page = max(1, min(per_page, 200))
    page = max(1, page)

    query, params = _build_contact_query(search, contact_type, letter, tags)

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
    query += f' ORDER BY is_favourite DESC, {order_col} {direction}'
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


def _mark_edited(db: sqlite3.Connection, contact_id: int) -> None:
    """Record a genuine user edit's timestamp in contact_edits (CL-0033).

    Called only by the user-facing writers (create_contact, _write_contact,
    import_contact) — never by the Google-sync pull — so edited_at stays an
    honest "last edited by you" signal, immune to a sync refreshing the row.
    Runs inside the caller's transaction (no commit of its own)."""
    db.execute(
        "INSERT INTO contact_edits (contact_id, edited_at) "
        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
        "ON CONFLICT(contact_id) DO UPDATE SET "
        "edited_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        [contact_id],
    )


def get_edited_at(db: sqlite3.Connection, contact_id: int) -> str | None:
    """The contact's last user-edit timestamp, or None if never user-edited."""
    row = db.execute(
        'SELECT edited_at FROM contact_edits WHERE contact_id = ?', [contact_id]
    ).fetchone()
    return row['edited_at'] if row else None


def get_dirty_linked(db: sqlite3.Connection, prev_sync: str | None) -> list[sqlite3.Row]:
    """Google-linked contacts the USER edited since the last sync — candidates
    for push-update (CL-0033). A NULL prev_sync (never synced) yields zero rows:
    nothing has diverged from a Google baseline yet, so the first sync only
    creates local-only contacts. The `:prev_sync IS NOT NULL` guard is
    belt-and-braces over SQLite's 3VL (`edited_at > NULL` is already NULL)."""
    return db.execute(
        'SELECT c.id, c.google_id FROM contacts c '
        'JOIN contact_edits e ON e.contact_id = c.id '
        'WHERE c.google_id IS NOT NULL '
        '  AND :prev IS NOT NULL AND e.edited_at > :prev',
        {'prev': prev_sync},
    ).fetchall()


def get_local_only_ids(db: sqlite3.Connection) -> list[int]:
    """Contacts with no google_id — candidates for push-create (all of them, so a
    new local contact reaches Google/the phone). CL-0033."""
    return [
        r['id'] for r in db.execute(
            'SELECT id FROM contacts WHERE google_id IS NULL ORDER BY id'
        )
    ]


def link_google_contact(
    db: sqlite3.Connection, contact_id: int, google_id: str, etag: str | None
) -> None:
    """Record the Google resourceName + etag after push-creating a contact, so a
    re-run updates rather than re-creates it (INV-6). Caller commits."""
    db.execute(
        'UPDATE contacts SET google_id = ?, etag = ? WHERE id = ?',
        [google_id, etag, contact_id],
    )


def set_contact_etag(db: sqlite3.Connection, contact_id: int, etag: str | None) -> None:
    """Store the fresh etag returned by a push-update. Caller commits."""
    db.execute('UPDATE contacts SET etag = ? WHERE id = ?', [etag, contact_id])


# Birthdays are stored as a 'birthday' custom field, either 'YYYY-MM-DD' or the
# year-less 'MM-DD' (see google_sync._upsert_person and DESIGN.md § data model).
_BIRTHDAY_RE = re.compile(r'^(?:(\d{4})-)?(\d{2})-(\d{2})$')


def _next_birthday(month: int, day: int, today: datetime.date) -> datetime.date:
    """Next occurrence of month/day on or after ``today``.

    Feb 29 is celebrated on Feb 28 in non-leap years so the birthday never
    silently disappears from the list.
    """
    def _make(year: int) -> datetime.date:
        try:
            return datetime.date(year, month, day)
        except ValueError:
            if month == 2 and day == 29:
                return datetime.date(year, 2, 28)
            raise

    candidate = _make(today.year)
    if candidate < today:
        candidate = _make(today.year + 1)
    return candidate


def upcoming_birthdays(
    db: sqlite3.Connection,
    within_days: int = 30,
    *,
    today: datetime.date | None = None,
) -> list[dict]:
    """Contacts whose 'birthday' custom field falls within the next N days.

    Returns dicts sorted by ``days_until`` ascending (ties broken by name).
    ``age`` is the age the contact will turn on that birthday, or None when no
    birth year was recorded. No schema change — reads existing custom_fields
    rows (CL-0038).
    """
    if today is None:
        today = datetime.date.today()
    rows = db.execute(
        "SELECT c.id, c.name, c.type, cf.field_value AS bday "
        "FROM custom_fields cf JOIN contacts c ON c.id = cf.contact_id "
        "WHERE cf.field_name = 'birthday' COLLATE NOCASE"
    ).fetchall()

    result: list[dict] = []
    for row in rows:
        match = _BIRTHDAY_RE.match((row['bday'] or '').strip())
        if not match:
            continue
        year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
        try:
            next_date = _next_birthday(month, day, today)
        except ValueError:
            continue  # impossible calendar date (e.g. 13-40)
        days_until = (next_date - today).days
        if days_until > within_days:
            continue
        result.append({
            'id': row['id'],
            'name': row['name'],
            'type': row['type'],
            'month': month,
            'day': day,
            'next_date': next_date,
            'days_until': days_until,
            'age': next_date.year - int(year) if year else None,
        })

    result.sort(key=lambda r: (r['days_until'], r['name'].casefold()))
    return result


def set_contact_photo(db: sqlite3.Connection, contact_id: int, ext: str) -> None:
    """Record (upsert) the stored photo extension for a contact (CL-0026).

    Caller commits. Must NOT commit itself: the Google-sync pull calls this from
    inside a per-contact ``SAVEPOINT person`` and a commit there destroys the
    savepoint, so the loop's ``RELEASE SAVEPOINT`` throws (CL-0045)."""
    db.execute(
        "INSERT INTO contact_photos (contact_id, ext) VALUES (?, ?) "
        "ON CONFLICT(contact_id) DO UPDATE SET "
        "ext = excluded.ext, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        [contact_id, ext],
    )


def get_contact_photo_ext(db: sqlite3.Connection, contact_id: int) -> str | None:
    """Return the stored photo extension for a contact, or None if it has none."""
    row = db.execute(
        'SELECT ext FROM contact_photos WHERE contact_id = ?', [contact_id]
    ).fetchone()
    return row['ext'] if row else None


def clear_contact_photo(db: sqlite3.Connection, contact_id: int) -> str | None:
    """Delete the photo row for a contact. Return the old ext (for the caller to
    unlink the file), or None if there was no photo. Caller commits (see
    set_contact_photo — same savepoint-safety reason, CL-0045)."""
    old_ext = get_contact_photo_ext(db, contact_id)
    if old_ext is not None:
        db.execute('DELETE FROM contact_photos WHERE contact_id = ?', [contact_id])
    return old_ext


def set_favourite(db: sqlite3.Connection, contact_id: int, favourite: bool) -> None:
    """Star (favourite=True) or un-star (False) a contact (CL-0039). Idempotent.

    Set-to-state, not a blind toggle: the caller passes the desired end state, so
    a double-submit converges rather than two rapid clicks cancelling out."""
    if favourite:
        db.execute(
            'INSERT OR IGNORE INTO contact_favourites (contact_id) VALUES (?)',
            [contact_id],
        )
    else:
        db.execute('DELETE FROM contact_favourites WHERE contact_id = ?', [contact_id])
    db.commit()


def is_favourite(db: sqlite3.Connection, contact_id: int) -> bool:
    """True iff the contact is currently a favourite (for the detail page)."""
    row = db.execute(
        'SELECT 1 FROM contact_favourites WHERE contact_id = ?', [contact_id]
    ).fetchone()
    return row is not None


def _normalize_tags(raw: str) -> list[str]:
    """Parse a comma-separated tag field into a clean, de-duplicated list (CL-0037).

    The single choke-point for what becomes a tag, so create/update/merge apply
    identical rules. Splits on commas; for each piece strips surrounding
    whitespace and collapses internal whitespace runs to one space; drops empties;
    truncates to MAX_TAG_LEN chars; de-duplicates case-insensitively preserving
    the first-seen casing and order; then keeps at most MAX_TAGS (dropping the
    surplus). Returns [] for a blank field.
    """
    out: list[str] = []
    seen: set[str] = set()
    for piece in raw.split(','):
        name = ' '.join(piece.split())  # strip + collapse internal whitespace
        if not name:
            continue
        name = name[:MAX_TAG_LEN]
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= MAX_TAGS:
            break
    return out


def _gc_orphan_tags(db: sqlite3.Connection) -> None:
    """Delete tag rows no contact references any more. No commit of its own — runs
    inside the caller's transaction. Global sweep, so any tag write also clears
    stragglers left by paths that don't GC inline (INV-3)."""
    db.execute('DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM contact_tags)')


def set_contact_tags(
    db: sqlite3.Connection, contact_id: int, tag_names: list[str]
) -> None:
    """Replace a contact's tag set with `tag_names` (already normalized).

    Upserts each name into `tags` (matched case-insensitively via the NOCASE
    UNIQUE), replaces the contact's `contact_tags` rows, then GCs orphans. NO
    transaction of its own — composes into the caller's `with db:` block, the same
    way _write_contact handles custom fields."""
    db.execute('DELETE FROM contact_tags WHERE contact_id = ?', [contact_id])
    for name in tag_names:
        db.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', [name])
        row = db.execute(
            'SELECT id FROM tags WHERE name = ? COLLATE NOCASE', [name]
        ).fetchone()
        db.execute(
            'INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)',
            [contact_id, row['id']],
        )
    _gc_orphan_tags(db)


def get_contact_tags(db: sqlite3.Connection, contact_id: int) -> list[str]:
    """The contact's tag names, ordered case-insensitively (for form + detail)."""
    rows = db.execute(
        'SELECT t.name FROM tags t JOIN contact_tags ct ON ct.tag_id = t.id '
        'WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE',
        [contact_id],
    ).fetchall()
    return [r['name'] for r in rows]


def get_all_tags(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every in-use tag with its contact count, for the list filter bar. The INNER
    JOIN excludes any orphan tag (0 contacts) independent of GC."""
    return db.execute(
        'SELECT t.name, COUNT(ct.contact_id) AS cnt '
        'FROM tags t JOIN contact_tags ct ON ct.tag_id = t.id '
        'GROUP BY t.id ORDER BY t.name COLLATE NOCASE'
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
    tags: list[str] | None = None,
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
        assert contact_id is not None  # lastrowid is always set after an INSERT
        if custom_fields:
            db.executemany(
                'INSERT INTO custom_fields (contact_id, field_name, field_value) VALUES (?, ?, ?)',
                [(contact_id, fn, fv) for fn, fv in custom_fields],
            )
        # create_contact has its own INSERT path (not via _write_contact), so it
        # makes its own tag write inside this transaction (CL-0037).
        set_contact_tags(db, contact_id, tags or [])
        _mark_edited(db, contact_id)
    return contact_id


def _write_contact(
    db: sqlite3.Connection,
    contact_id: int,
    contact_type: str,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    custom_fields: list[tuple[str, str]] | None = None,
    tags: list[str] | None = None,
) -> None:
    """Validate, UPDATE a contact, and replace its custom fields + tags — WITHOUT a
    transaction of its own, so a caller can compose it into a larger atomic
    block. `update_contact` wraps this in `with db:`; `merge_contacts` runs it
    alongside the loser deletes in one transaction. Validating here means every
    caller enforces the same contract (INV-4)."""
    _validate_contact_type(contact_type)
    _validate_custom_field_names(custom_fields)

    db.execute(
        """UPDATE contacts
           SET type=?, name=?, email=?, phone=?, notes=?,
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
           WHERE id=?""",
        [contact_type, name, email, phone, notes, contact_id],
    )
    db.execute('DELETE FROM custom_fields WHERE contact_id = ?', [contact_id])
    if custom_fields:
        db.executemany(
            'INSERT INTO custom_fields (contact_id, field_name, field_value) VALUES (?, ?, ?)',
            [(contact_id, fn, fv) for fn, fv in custom_fields],
        )
    set_contact_tags(db, contact_id, tags or [])  # CL-0037
    # _write_contact backs update_contact AND merge_contacts (survivor); both are
    # genuine user edits, so mark the row edited (CL-0033). create_contact and
    # import_contact INSERT directly (not via here), so they mark separately.
    _mark_edited(db, contact_id)


def update_contact(
    db: sqlite3.Connection,
    contact_id: int,
    contact_type: str,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    custom_fields: list[tuple[str, str]] | None = None,
    tags: list[str] | None = None,
) -> None:
    # `with db` makes the UPDATE + DELETE + re-insert atomic: if the re-insert
    # fails, the delete of the old custom fields is rolled back too, so a failed
    # update can't silently wipe a contact's existing custom fields.
    with db:
        _write_contact(
            db, contact_id, contact_type, name, email, phone, notes,
            custom_fields, tags,
        )


def delete_contact(db: sqlite3.Connection, contact_id: int) -> None:
    with db:
        db.execute('DELETE FROM contacts WHERE id = ?', [contact_id])
        _gc_orphan_tags(db)  # CL-0037: reap a tag this contact was the last user of


_FIELD_NAME_RE = re.compile(r'^[a-zA-Z0-9_ ]{1,64}$')
_FIELD_NAME_STRIP_RE = re.compile(r'[^a-zA-Z0-9_ ]+')


def valid_field_name(name: str) -> bool:
    return bool(_FIELD_NAME_RE.match(name))


def sanitize_field_name(raw: str) -> str:
    """Coerce an arbitrary label (a CSV header, a vCard TYPE) into a name that
    passes `valid_field_name`: drop any char outside [a-zA-Z0-9_ ], collapse
    whitespace, trim, cap at 64. Returns '' if nothing survives — the caller
    then falls back to a generated name (e.g. 'Field 2')."""
    cleaned = _FIELD_NAME_STRIP_RE.sub(' ', raw)
    return ' '.join(cleaned.split())[:64]


def import_contact(
    db: sqlite3.Connection,
    fields: dict,
    custom_fields: list[tuple[str, str]] | None = None,
) -> tuple[int, str]:
    """Create a contact, or additively update an existing match, from one parsed
    import row. Matches an existing contact by email (case-insensitive) else by
    name; on a match, fills only blank core fields and adds only
    not-yet-present custom-field names — never overwrites (INV-1). Returns
    (contact_id, 'created' | 'updated'). Takes a parsed dict because the
    importer builds fields dynamically from the column mapping."""
    contact_type = (fields.get('type') or '').strip() or 'individual'
    _validate_contact_type(contact_type)
    name = (fields.get('name') or '').strip()
    email = (fields.get('email') or '').strip() or None
    phone = (fields.get('phone') or '').strip() or None
    notes = (fields.get('notes') or '').strip() or None
    custom_fields = custom_fields or []
    _validate_custom_field_names(custom_fields)

    match_id: int | None = None
    if email:
        row = db.execute(
            "SELECT id FROM contacts "
            "WHERE email IS NOT NULL AND email != '' AND LOWER(email) = LOWER(?) "
            "ORDER BY id LIMIT 1",
            [email],
        ).fetchone()
        if row:
            match_id = row['id']
    if match_id is None and name:
        row = db.execute(
            'SELECT id FROM contacts WHERE name = ? COLLATE NOCASE ORDER BY id LIMIT 1',
            [name],
        ).fetchone()
        if row:
            match_id = row['id']

    with db:
        if match_id is None:
            cursor = db.execute(
                'INSERT INTO contacts (type, name, email, phone, notes) VALUES (?, ?, ?, ?, ?)',
                [contact_type, name, email, phone, notes],
            )
            new_id = cursor.lastrowid
            assert new_id is not None
            if custom_fields:
                db.executemany(
                    'INSERT INTO custom_fields (contact_id, field_name, field_value) '
                    'VALUES (?, ?, ?)',
                    [(new_id, fn, fv) for fn, fv in custom_fields],
                )
            _mark_edited(db, new_id)
            return new_id, 'created'

        # Additive update: fill a core field only when the existing value is
        # blank; keep the existing value otherwise (never overwrite).
        existing = db.execute(
            'SELECT email, phone, notes FROM contacts WHERE id = ?', [match_id]
        ).fetchone()
        def _fill(new: str | None, old: str | None) -> str | None:
            return new if (new and not (old or '').strip()) else old

        new_email = _fill(email, existing['email'])
        new_phone = _fill(phone, existing['phone'])
        new_notes = _fill(notes, existing['notes'])
        current = (existing['email'], existing['phone'], existing['notes'])
        core_changed = (new_email, new_phone, new_notes) != current
        if core_changed:
            db.execute(
                "UPDATE contacts SET email=?, phone=?, notes=?, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id=?",
                [new_email, new_phone, new_notes, match_id],
            )
        # Add only custom-field names the contact doesn't already have
        # (case-insensitive, matching idx_cf_unique).
        existing_names = {
            r['field_name'].lower()
            for r in db.execute(
                'SELECT field_name FROM custom_fields WHERE contact_id = ?', [match_id]
            )
        }
        to_add = [
            (match_id, fn, fv) for fn, fv in custom_fields if fn.lower() not in existing_names
        ]
        if to_add:
            db.executemany(
                'INSERT INTO custom_fields (contact_id, field_name, field_value) '
                'VALUES (?, ?, ?)',
                to_add,
            )
        # Mark edited only when the import actually changed data — a pure no-op
        # match must not move edited_at (CL-0033).
        if core_changed or to_add:
            _mark_edited(db, match_id)
        return match_id, 'updated'


def merge_contacts(
    db: sqlite3.Connection,
    survivor_id: int,
    loser_ids: list[int],
    fields: dict,
    custom_fields: list[tuple[str, str]] | None = None,
    tags: list[str] | None = None,
) -> None:
    """Merge `loser_ids` into `survivor_id`: overwrite the survivor with the
    chosen `fields` + `custom_fields` + `tags`, then delete the losers (their
    custom fields / tag links cascade via the FK). One `with db:` block makes it
    atomic (INV-3); `_write_contact` carries the validation (INV-4)."""
    losers = list(dict.fromkeys(loser_ids))  # de-dupe, preserve order
    if not losers:
        raise ValueError('merge needs at least one other contact')
    if survivor_id in losers:
        raise ValueError('survivor cannot also be a loser')
    ids = [survivor_id, *losers]
    placeholders = ','.join('?' * len(ids))
    found = {
        r['id']
        for r in db.execute(
            f'SELECT id FROM contacts WHERE id IN ({placeholders})', ids
        )
    }
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f'contact id(s) not found: {missing}')

    with db:
        _write_contact(
            db, survivor_id, fields['type'], fields['name'],
            fields.get('email'), fields.get('phone'), fields.get('notes'),
            custom_fields, tags,
        )
        for lid in losers:
            db.execute('DELETE FROM contacts WHERE id = ?', [lid])
        # The survivor's tag write GC'd before the losers were deleted, so a
        # loser-only tag the user pruned still had the loser's link then. Sweep
        # again now that the loser links have cascaded away (CL-0037, INV-3).
        _gc_orphan_tags(db)


def get_import_profile(db: sqlite3.Connection, header_signature: str) -> dict | None:
    """Return a saved CSV column-mapping profile for this header layout, or None."""
    row = db.execute(
        'SELECT mapping, default_type FROM import_profiles WHERE header_signature = ?',
        [header_signature],
    ).fetchone()
    if row is None:
        return None
    return {'mapping': json.loads(row['mapping']), 'default_type': row['default_type']}


def save_import_profile(
    db: sqlite3.Connection, header_signature: str, mapping: dict, default_type: str
) -> None:
    """Upsert the chosen column mapping for this header layout (CL-0022)."""
    with db:
        db.execute(
            'INSERT INTO import_profiles (header_signature, mapping, default_type) '
            'VALUES (?, ?, ?) '
            'ON CONFLICT(header_signature) DO UPDATE SET '
            "mapping=excluded.mapping, default_type=excluded.default_type, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
            [header_signature, json.dumps(mapping), default_type],
        )
