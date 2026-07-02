from __future__ import annotations

import logging
import os
import sqlite3
import urllib.parse
import urllib.request

import models
import phoneutil
import photos

log = logging.getLogger(__name__)

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


def sync_contacts(config: dict, db: sqlite3.Connection, region: str) -> tuple[int, str | None]:
    """Import contacts from Google. Returns (count_synced, error_or_none)."""
    creds = _load_credentials(config)
    if not creds:
        return 0, 'Not authenticated with Google.'

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    service = build('people', 'v1', credentials=creds, cache_discovery=False)

    row = db.execute('SELECT sync_token FROM sync_state WHERE id = 1').fetchone()
    sync_token: str | None = row['sync_token'] if row else None

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
            return synced, 'A Google API error occurred. Check the logs for details.'
        except Exception:
            log.exception('Google Contacts sync failed')
            return synced, 'A Google API error occurred. Check the logs for details.'

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
                imported = _upsert_person(db, person, region, config)
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

    if new_sync_token:
        db.execute(
            """INSERT INTO sync_state (id, sync_token, last_synced_at)
               VALUES (1, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
               ON CONFLICT(id) DO UPDATE SET
                   sync_token = excluded.sync_token,
                   last_synced_at = excluded.last_synced_at""",
            [new_sync_token],
        )

    db.commit()
    log.info('Sync complete: %d contact(s) synced', synced)
    return synced, None


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


def _upsert_person(db: sqlite3.Connection, person: dict, region: str, config) -> bool:
    """Import one Google person. Returns True if a contact was imported/updated,
    False for a delete tombstone or a record with no usable name."""
    metadata = person.get('metadata', {})
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
