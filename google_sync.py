from __future__ import annotations

import datetime
import logging
import os
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass

import models
import phoneutil
import photos

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Outcome of one bidirectional sync (CL-0033). Replaces the old
    (count, error) tuple; the /sync route reads it by attribute."""
    pulled: int = 0            # contacts imported/updated from Google
    created: int = 0           # local-only contacts created on Google
    updated: int = 0           # linked contacts updated on Google
    conflicts_google: int = 0  # conflicts resolved Google-wins
    conflicts_local: int = 0   # conflicts resolved local-wins
    skipped: int = 0           # per-contact push failures (logged, not fatal)
    push_no_time: int = 0      # linked contacts whose Google updateTime was absent
    error: str | None = None   # fatal error (else None)

# Read-WRITE scope (CL-0033): covers reading too, so the old .readonly scope is
# dropped. Single source of truth — google_auth.py imports this constant, so the
# two modules can never request different scopes (INV-5).
SCOPES = ['https://www.googleapis.com/auth/contacts']


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def has_credentials(config: dict) -> bool:
    return os.path.isfile(config['GOOGLE_CREDENTIALS_FILE'])


def _token_has_write_scope(config: dict) -> bool:
    """True iff a token file exists AND its OWN recorded scopes include the write
    scope. Reads the token file's scopes via a throwaway probe with the scopes
    arg OMITTED — passing SCOPES would make ``creds.scopes`` echo the argument and
    ``has_scopes`` return True tautologically, masking a legacy read-only token
    (CL-0033 §3). A token file with no ``scopes`` key → probe.scopes is None →
    has_scopes False → treated as needing re-consent."""
    token_path = config['GOOGLE_TOKEN_FILE']
    if not os.path.isfile(token_path):
        return False
    from google.oauth2.credentials import Credentials
    try:
        probe = Credentials.from_authorized_user_file(token_path)
    except Exception:
        return False
    return bool(probe.has_scopes(SCOPES))


def needs_reconsent(config: dict) -> bool:
    """True when a token exists but lacks the write scope (a legacy read-only
    token, or one missing its scopes) — so the /sync page can prompt a reconnect
    rather than the plain first-time authorise. False when there is no token."""
    return os.path.isfile(config['GOOGLE_TOKEN_FILE']) and not _token_has_write_scope(config)


def is_authenticated(config: dict) -> bool:
    creds = _load_credentials(config)
    return creds is not None and creds.valid


def _load_credentials(config: dict):
    """Load and refresh stored OAuth credentials. Returns None if unavailable."""
    token_path = config['GOOGLE_TOKEN_FILE']
    if not os.path.isfile(token_path):
        return None
    # A legacy token minted for the read-only scope can't authorise writes and
    # would 403; treat it as no token so the app shows the reconnect path.
    if not _token_has_write_scope(config):
        return None

    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request

        try:
            creds.refresh(Request())
            _save_credentials(config, creds)
        except Exception:
            log.exception('Failed to refresh Google token')
            return None
    return creds if creds.valid else None


def _save_credentials(config: dict, creds) -> None:
    from config import ensure_private_dir

    token_path = config['GOOGLE_TOKEN_FILE']
    ensure_private_dir(os.path.dirname(token_path))
    # Create with 0600 from the start so the token is never briefly
    # world-readable between write and chmod (the chmod still covers the
    # case where the file already existed with looser permissions).
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(creds.to_json())
    os.chmod(token_path, 0o600)


def revoke_credentials(config: dict) -> None:
    token_path = config['GOOGLE_TOKEN_FILE']
    if os.path.isfile(token_path):
        os.remove(token_path)


# ---------------------------------------------------------------------------
# Contact sync
# ---------------------------------------------------------------------------

def _is_expired_sync_token(exc) -> bool:
    """True if ``exc`` is the People API's expired-sync-token error.

    The People API returns HTTP 400 with the machine-readable reason
    ``EXPIRED_SYNC_TOKEN`` when a stored delta token is too old. Matching on the
    status + reason (not a substring of the human message) keeps self-healing
    working even if Google rewords the message (CL-0009). Uses duck-typing so it
    doesn't need googleapiclient imported at module load.
    """
    resp = getattr(exc, 'resp', None)
    status = getattr(resp, 'status', None)
    if status is None:
        status = getattr(exc, 'status_code', None)
    if status != 400:
        return False
    content = getattr(exc, 'content', b'') or b''
    if isinstance(content, bytes):
        content = content.decode('utf-8', 'replace')
    return 'EXPIRED_SYNC_TOKEN' in content


def sync_contacts(config: dict, db: sqlite3.Connection, region: str) -> SyncResult:
    """Bidirectional Google Contacts sync (CL-0033): pull changed Google contacts,
    then push local creates + edits back. Returns a SyncResult."""
    creds = _load_credentials(config)
    if not creds:
        return SyncResult(error='Not authenticated with Google.')

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    service = build('people', 'v1', credentials=creds, cache_discovery=False)

    result = SyncResult()

    # --- Step 0: snapshot BEFORE the pull writes or Step 3 advances the baseline.
    # prev_sync is captured now because Step 3 overwrites last_synced_at; the dirty
    # sets are computed once here and never recomputed after that advance.
    row = db.execute(
        'SELECT sync_token, last_synced_at FROM sync_state WHERE id = 1'
    ).fetchone()
    sync_token: str | None = row['sync_token'] if row else None
    prev_sync: str | None = row['last_synced_at'] if row else None
    dirty_linked = models.get_dirty_linked(db, prev_sync)
    dirty_google_ids = frozenset(
        r['google_id'] for r in dirty_linked if r['google_id']
    )
    local_only = models.get_local_only_ids(db)

    log.info('Starting Google Contacts sync')

    synced = 0
    next_page_token: str | None = None
    new_sync_token: str | None = None

    while True:
        kwargs: dict = {
            'resourceName': 'people/me',
            'pageSize': 1000,
            'personFields': (
                'names,emailAddresses,phoneNumbers,'
                'organizations,biographies,birthdays,addresses,photos'
            ),
            'requestSyncToken': True,
        }
        if sync_token:
            kwargs['syncToken'] = sync_token
        if next_page_token:
            kwargs['pageToken'] = next_page_token

        try:
            results = service.people().connections().list(**kwargs).execute()
        except HttpError as exc:
            if sync_token and synced == 0 and _is_expired_sync_token(exc):
                # Expired sync token: restart a clean full resync from page 1.
                # Reset the page cursor and count too, or the retry would reuse
                # a stale pageToken from the delta attempt and miscount. The
                # `synced == 0` guard enforces in code what the People API
                # guarantees (the token is validated on the first request): the
                # reset can only run before any page has been committed, so it
                # can never discard already-imported pages.
                sync_token = None
                next_page_token = None
                synced = 0
                db.execute('DELETE FROM sync_state WHERE id = 1')
                db.commit()
                continue
            # Log the detail server-side; don't surface raw API error text
            # (which can include request URLs / error JSON) to the user. Return
            # what was already committed rather than 0 (CL-0020).
            log.exception('Google Contacts sync failed')
            result.pulled = synced
            result.error = 'A Google API error occurred. Check the logs for details.'
            return result
        except Exception:
            log.exception('Google Contacts sync failed')
            result.pulled = synced
            result.error = 'A Google API error occurred. Check the logs for details.'
            return result

        for person in results.get('connections', []):
            # Isolate each contact in its own SAVEPOINT: a malformed record must
            # not abort the run, nor leave a half-applied upsert behind (the
            # upsert does UPDATE + DELETE custom_fields + INSERT, which has to be
            # all-or-nothing or the contact silently loses its custom fields).
            # NOTE: the SAVEPOINT/ROLLBACK isolation relies on Python 3.12+
            # sqlite3 transaction semantics (see DESIGN.md §3); on legacy
            # (<=3.11) sqlite3 a SAVEPOINT in autocommit can weaken the rollback.
            try:
                db.execute('SAVEPOINT person')
                imported = _upsert_person(db, person, region, config, dirty_google_ids)
                db.execute('RELEASE SAVEPOINT person')
            except Exception:
                db.execute('ROLLBACK TO SAVEPOINT person')
                db.execute('RELEASE SAVEPOINT person')
                log.exception('Skipping a contact that failed to import')
            else:
                if imported:
                    synced += 1

        # Commit each page before fetching the next, so a transient API error on
        # a later page can't discard contacts already imported. Safe because the
        # upsert is idempotent on google_id — a re-run re-applies cleanly (CL-0020).
        db.commit()

        next_page_token = results.get('nextPageToken')
        # Never let a None on a later page clobber a token seen earlier.
        new_sync_token = results.get('nextSyncToken') or new_sync_token

        if not next_page_token:
            break

    result.pulled = synced

    # --- Step 2: push local changes back to Google (per-contact commits inside).
    _push_local_changes(service, db, region, config, dirty_linked, local_only,
                        prev_sync, result)

    # --- Step 3: finalise. last_synced_at advances UNCONDITIONALLY on a clean
    # finish (decoupled from the sync-token write), or the next run's prev_sync is
    # stale and re-pushes edits it already pushed. sync_token updates only when a
    # new one was returned.
    db.execute(
        """INSERT INTO sync_state (id, sync_token, last_synced_at)
           VALUES (1, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
           ON CONFLICT(id) DO UPDATE SET
               sync_token = COALESCE(excluded.sync_token, sync_state.sync_token),
               last_synced_at = excluded.last_synced_at""",
        [new_sync_token],
    )
    db.commit()
    log.info('Sync complete: pulled=%d created=%d updated=%d',
             result.pulled, result.created, result.updated)
    return result


# ---------------------------------------------------------------------------
# Push phase (local -> Google)
# ---------------------------------------------------------------------------

# The only fields the app reads or writes; updatePersonFields never lists anything
# outside this set, so Google-side data we don't manage is untouched (INV-2).
_MANAGED_FIELDS = (
    'names,emailAddresses,phoneNumbers,biographies,birthdays,addresses,organizations'
)


def _parse_dt(value: str | None) -> datetime.datetime | None:
    """Parse an app timestamp ('...Z', second precision) or a Google RFC3339
    updateTime (fractional seconds / offset) into a UTC-aware datetime. Comparing
    parsed datetimes — not strings — avoids mis-ordering ...123456Z vs ...00Z."""
    if not value:
        return None
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _contact_update_time(person: dict) -> datetime.datetime | None:
    """Google's last-edit time for a contact — the CONTACT-source updateTime,
    returned automatically on a get() (not a personFields value). None if absent."""
    for src in person.get('metadata', {}).get('sources', []):
        if src.get('type') == 'CONTACT' and src.get('updateTime'):
            return _parse_dt(src['updateTime'])
    return None


def _merge_primary(existing: list | None, value: str, key: str) -> list:
    """Set the value of the FIRST entry (index 0) in place, preserving its other
    keys and every later entry — the multi-value-preservation guard (INV-2). If
    the list is empty, create one entry. Position-based (not value-matching): the
    app imports index 0 and re-formats phones, so a value-equality match could
    silently clobber the wrong entry."""
    entries = [dict(e) for e in (existing or [])]
    if entries:
        entries[0][key] = value
    else:
        entries = [{key: value}]
    return entries


def _birthday_to_google_date(value: str) -> dict | None:
    """'YYYY-MM-DD' or 'MM-DD' -> a People API date {year?, month, day}."""
    match = models._BIRTHDAY_RE.match((value or '').strip())
    if not match:
        return None
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
    date = {'month': month, 'day': day}
    if year:
        date['year'] = int(year)
    return date


def _person_body_for_push(
    contact: sqlite3.Row, custom_fields: list, existing: dict | None
) -> tuple[dict, list[str]]:
    """Build a People API person body + the list of personFields being written,
    from a local contact. `existing` is the live Google person (update, to preserve
    multi-values) or None (create). Only managed fields are ever written."""
    existing = existing or {}
    body: dict = {}
    fields: list[str] = []

    if contact['name']:
        body['names'] = _merge_primary(existing.get('names'), contact['name'],
                                       'unstructuredName')
        fields.append('names')
    if contact['email']:
        body['emailAddresses'] = _merge_primary(
            existing.get('emailAddresses'), contact['email'], 'value')
        fields.append('emailAddresses')
    if contact['phone']:
        body['phoneNumbers'] = _merge_primary(
            existing.get('phoneNumbers'), contact['phone'], 'value')
        fields.append('phoneNumbers')
    if contact['notes']:
        body['biographies'] = _merge_primary(
            existing.get('biographies'), contact['notes'], 'value')
        fields.append('biographies')

    cf = {r['field_name'].lower(): r['field_value'] for r in custom_fields}
    date = _birthday_to_google_date(cf['birthday']) if cf.get('birthday') else None
    if date:
        body['birthdays'] = [{'date': date}]  # single-valued
        fields.append('birthdays')
    if cf.get('address'):
        body['addresses'] = _merge_primary(
            existing.get('addresses'), cf['address'], 'formattedValue')
        fields.append('addresses')
    # organizations only from the explicit custom field; a type=company contact's
    # org name already lives in `name`->`names`, so don't duplicate it (§6).
    if cf.get('organization'):
        body['organizations'] = _merge_primary(
            existing.get('organizations'), cf['organization'], 'name')
        fields.append('organizations')

    return body, fields


def _apply_google_to_local(db, person: dict, region: str, config) -> None:
    """Overwrite the local row with Google's copy (a Google-wins conflict). Reuses
    the pull's upsert, so it writes updated_at, never edited_at (INV-1)."""
    db.execute('SAVEPOINT applygoogle')
    try:
        _upsert_person(db, person, region, config)
        db.execute('RELEASE SAVEPOINT applygoogle')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT applygoogle')
        db.execute('RELEASE SAVEPOINT applygoogle')
        raise


def _push_update(service, db, contact_id: int, google_id: str, person: dict) -> bool:
    """updateContact with the fresh etag + a preserving body. Returns True if a
    write happened (False when there was nothing managed to write)."""
    contact = models.get_contact(db, contact_id)
    if not contact:
        return False
    cfs = models.get_custom_fields(db, contact_id)
    body, fields = _person_body_for_push(contact, cfs, person)
    if not fields:
        return False
    body['etag'] = person.get('etag')
    updated = service.people().updateContact(
        resourceName=google_id, updatePersonFields=','.join(fields), body=body,
    ).execute()
    models.set_contact_etag(db, contact_id, updated.get('etag'))
    db.commit()
    return True


def _push_local_changes(service, db, region, config, dirty_linked, local_only,
                        prev_sync, result: SyncResult) -> None:
    """Step 2: create local-only contacts on Google, and push locally-edited
    linked contacts with per-contact conflict resolution (§7). Each push is its own
    committed unit, isolated so one failure is logged + skipped, never fatal."""
    prev_dt = _parse_dt(prev_sync)

    for contact_id in local_only:
        try:
            contact = models.get_contact(db, contact_id)
            if not contact:
                continue
            cfs = models.get_custom_fields(db, contact_id)
            body, _fields = _person_body_for_push(contact, cfs, None)
            created = service.people().createContact(body=body).execute()
            models.link_google_contact(
                db, contact_id, created.get('resourceName'), created.get('etag'))
            db.commit()  # persist the link at once so a re-run never re-creates
            result.created += 1
        except Exception:
            db.rollback()
            log.exception('Failed to create Google contact for %s', contact_id)
            result.skipped += 1

    for row in dirty_linked:
        contact_id, google_id = row['id'], row['google_id']
        try:
            person = service.people().get(
                resourceName=google_id, personFields=_MANAGED_FIELDS,
            ).execute()
            google_dt = _contact_update_time(person)
            if google_dt is None:
                # Can't prove our edit is newer -> Google-wins, don't push. Counted
                # so a systematic absence is visible, not a silent one-way sync.
                result.push_no_time += 1
                continue
            local_dt = _parse_dt(models.get_edited_at(db, contact_id))
            google_changed = prev_dt is None or google_dt > prev_dt
            if google_changed and not (local_dt is not None and local_dt > google_dt):
                # Both changed and Google is newer-or-equal -> Google wins.
                _apply_google_to_local(db, person, region, config)
                db.commit()
                result.conflicts_google += 1
            else:
                pushed = _push_update(service, db, contact_id, google_id, person)
                if pushed and google_changed:
                    result.conflicts_local += 1  # local edit beat a concurrent Google edit
                elif pushed:
                    result.updated += 1
        except Exception:
            db.rollback()
            log.exception('Failed to push contact %s', contact_id)
            result.skipped += 1


def _fetch_photo_bytes(url: str) -> bytes:
    """Download at most MAX_PHOTO_BYTES + 1 bytes from a photo URL (stdlib only).

    The +1 lets the size check detect an oversize body without buffering the
    whole stream. Wrapped by the caller in try/except so a failure is non-fatal.
    """
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 (host is validated by caller)
        return resp.read(photos.MAX_PHOTO_BYTES + 1)


def _store_person_photo(config, db: sqlite3.Connection, contact_id: int, person: dict) -> None:
    """Download and store the first real (non-default) Google photo, if any.

    Non-fatal: any network/validation error is logged and swallowed so it never
    aborts the contact import (INV-5). Only https ``*.googleusercontent.com``
    URLs are fetched (SSRF guard, INV-6)."""
    for entry in person.get('photos', []):
        if entry.get('default'):
            continue  # Google's generated silhouette — worse than our initials
        url = entry.get('url')
        if not url:
            continue
        host = urllib.parse.urlparse(url).hostname or ''
        if urllib.parse.urlparse(url).scheme != 'https' or not (
            host == 'googleusercontent.com' or host.endswith('.googleusercontent.com')
        ):
            continue
        try:
            data = _fetch_photo_bytes(url)
            old_ext = models.get_contact_photo_ext(db, contact_id)
            ext = photos.save_photo(config, contact_id, data, old_ext=old_ext)
        except Exception:
            log.warning('Skipping photo for contact %s (download/validation failed)', contact_id)
            return
        models.set_contact_photo(db, contact_id, ext)
        return  # first usable photo only


def _upsert_person(
    db: sqlite3.Connection, person: dict, region: str, config,
    skip_google_ids: frozenset[str] = frozenset(),
) -> bool:
    """Import one Google person. Returns True if a contact was imported/updated,
    False for a delete tombstone, a record with no usable name, or a deferred one.

    A resourceName in skip_google_ids is a locally-edited contact whose pull we
    DEFER so the local edit survives for the push phase to resolve (CL-0033)."""
    metadata = person.get('metadata', {})
    if person.get('resourceName') in skip_google_ids:
        return False
    google_id = person.get('resourceName')

    if metadata.get('deleted'):
        if google_id:
            db.execute('DELETE FROM contacts WHERE google_id = ?', [google_id])
        return False

    names = person.get('names', [])
    name = names[0].get('displayName', '') if names else ''
    if not name:
        return False

    etag = person.get('etag')
    emails = person.get('emailAddresses', [])
    email = emails[0].get('value') if emails else None
    phones = person.get('phoneNumbers', [])
    value = phones[0].get('value') if phones else None
    phone = phoneutil.format_phone(value, region) if value else value
    orgs = person.get('organizations', [])
    org_name = orgs[0].get('name', '') if orgs else ''
    # Classify as a company when there's an organization but no personal name.
    # A record carrying a given/family name is a person (even if they list an
    # employer); the old exact org==displayName check missed most companies,
    # which have no personal name at all (CL-0010).
    name_fields = names[0] if names else {}
    has_personal_name = bool(name_fields.get('givenName') or name_fields.get('familyName'))
    contact_type = 'company' if (org_name and not has_personal_name) else 'individual'
    bios = person.get('biographies', [])
    notes = bios[0].get('value') if bios else None

    existing = db.execute(
        'SELECT id FROM contacts WHERE google_id = ?', [google_id]
    ).fetchone()

    if existing:
        contact_id = existing['id']
        db.execute(
            """UPDATE contacts
               SET type=?, name=?, email=?, phone=?, notes=?, etag=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
               WHERE id=?""",
            [contact_type, name, email, phone, notes, etag, contact_id],
        )
        db.execute(
            "DELETE FROM custom_fields WHERE contact_id = ? "
            "AND field_name IN ('birthday', 'address', 'organization')",
            [contact_id],
        )
    else:
        cursor = db.execute(
            'INSERT INTO contacts (type, name, email, phone, notes, google_id, etag) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            [contact_type, name, email, phone, notes, google_id, etag],
        )
        contact_id = cursor.lastrowid

    # Custom fields from Google data
    cf: list[tuple[int, str, str]] = []

    birthdays = person.get('birthdays', [])
    if birthdays:
        bday = birthdays[0].get('date', {})
        month, day = bday.get('month'), bday.get('day')
        # Only store a birthday when month+day are present (don't fabricate
        # Jan 1). Year is optional in the People API — omit it cleanly rather
        # than emit a non-ISO "????-MM-DD".
        if month and day:
            year = bday.get('year')
            value = f'{year:04d}-{month:02d}-{day:02d}' if year else f'{month:02d}-{day:02d}'
            cf.append((contact_id, 'birthday', value))

    addresses = person.get('addresses', [])
    if addresses:
        addr = addresses[0].get('formattedValue', '')
        if addr:
            cf.append((contact_id, 'address', addr))

    if orgs:
        org_name = orgs[0].get('name', '')
        if org_name:
            cf.append((contact_id, 'organization', org_name))

    if cf:
        db.executemany(
            'INSERT INTO custom_fields (contact_id, field_name, field_value) '
            'VALUES (?, ?, ?)',
            cf,
        )

    _store_person_photo(config, db, contact_id, person)

    return True
