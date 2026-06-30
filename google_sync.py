from __future__ import annotations

import logging
import os
import sqlite3

log = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/contacts.readonly']
DEFAULT_REGION = 'ZA'


def _format_phone(raw: str | None) -> str | None:
    """Format a phone number to international format."""
    if not raw:
        return None
    try:
        import phonenumbers
        parsed = phonenumbers.parse(raw, DEFAULT_REGION)
        if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        pass
    return raw


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def has_credentials(config: dict) -> bool:
    return os.path.isfile(config['GOOGLE_CREDENTIALS_FILE'])


def is_authenticated(config: dict) -> bool:
    creds = _load_credentials(config)
    return creds is not None and creds.valid


def _load_credentials(config: dict):
    """Load and refresh stored OAuth credentials. Returns None if unavailable."""
    token_path = config['GOOGLE_TOKEN_FILE']
    if not os.path.isfile(token_path):
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
    token_path = config['GOOGLE_TOKEN_FILE']
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, 'w') as f:
        f.write(creds.to_json())
    os.chmod(token_path, 0o600)


def revoke_credentials(config: dict) -> None:
    token_path = config['GOOGLE_TOKEN_FILE']
    if os.path.isfile(token_path):
        os.remove(token_path)


# ---------------------------------------------------------------------------
# Contact sync
# ---------------------------------------------------------------------------

def sync_contacts(config: dict, db: sqlite3.Connection) -> tuple[int, str | None]:
    """Import contacts from Google. Returns (count_synced, error_or_none)."""
    creds = _load_credentials(config)
    if not creds:
        return 0, 'Not authenticated with Google.'

    from googleapiclient.discovery import build

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
                'organizations,biographies,birthdays,addresses'
            ),
            'requestSyncToken': True,
        }
        if sync_token:
            kwargs['syncToken'] = sync_token
        if next_page_token:
            kwargs['pageToken'] = next_page_token

        try:
            results = service.people().connections().list(**kwargs).execute()
        except Exception as exc:
            if 'Sync token' in str(exc) and sync_token:
                sync_token = None
                db.execute('DELETE FROM sync_state WHERE id = 1')
                db.commit()
                continue
            return 0, str(exc)

        for person in results.get('connections', []):
            _upsert_person(db, person)
            synced += 1

        next_page_token = results.get('nextPageToken')
        new_sync_token = results.get('nextSyncToken')

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


def _upsert_person(db: sqlite3.Connection, person: dict) -> None:
    metadata = person.get('metadata', {})
    google_id = person.get('resourceName')

    if metadata.get('deleted'):
        if google_id:
            db.execute('DELETE FROM contacts WHERE google_id = ?', [google_id])
        return

    names = person.get('names', [])
    name = names[0].get('displayName', '') if names else ''
    if not name:
        return

    etag = person.get('etag')
    emails = person.get('emailAddresses', [])
    email = emails[0].get('value') if emails else None
    phones = person.get('phoneNumbers', [])
    phone = _format_phone(phones[0].get('value')) if phones else None
    orgs = person.get('organizations', [])
    org_name = orgs[0].get('name', '') if orgs else ''
    contact_type = 'company' if org_name and org_name == name else 'individual'
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
        if bday:
            year = bday.get('year', '????')
            month = bday.get('month', 1)
            day = bday.get('day', 1)
            cf.append((contact_id, 'birthday', f'{year}-{month:02d}-{day:02d}'))

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
