"""Tests for the audit/review hardening follow-ups (CL-0008..CL-0021)."""

from __future__ import annotations

import os
import stat

import pytest

from app import create_app
from db import get_db


@pytest.fixture()
def app(tmp_path):
    db_path = str(tmp_path / 'test.db')
    gcreds = tmp_path / 'gcreds'
    app = create_app({
        'TESTING': True,
        'DATABASE': db_path,
        'SECRET_KEY': 'test-secret',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })
    yield app


@pytest.fixture()
def db(app):
    with app.app_context():
        yield get_db()


class _FakeResp:
    """Minimal stand-in for an httplib2 Response (status + reason)."""

    def __init__(self, status):
        self.status = status
        self.reason = 'error'


class _FakeHttpError:
    """Duck-typed HttpError for _is_expired_sync_token (which uses getattr)."""

    def __init__(self, status, content):
        self.resp = _FakeResp(status)
        self.content = content


class TestExpiredSyncTokenDetection:
    def test_400_with_reason_is_expired(self):
        import google_sync
        exc = _FakeHttpError(400, b'{"error":{"status":"INVALID_ARGUMENT",'
                                  b'"details":[{"reason":"EXPIRED_SYNC_TOKEN"}]}}')
        assert google_sync._is_expired_sync_token(exc) is True

    def test_400_without_reason_is_not_expired(self):
        import google_sync
        exc = _FakeHttpError(400, b'{"error":{"message":"some other 400"}}')
        assert google_sync._is_expired_sync_token(exc) is False

    def test_500_is_not_expired(self):
        import google_sync
        exc = _FakeHttpError(500, b'EXPIRED_SYNC_TOKEN')  # wrong status
        assert google_sync._is_expired_sync_token(exc) is False


class TestCompanyDetection:
    def test_org_without_personal_name_is_company(self, db):
        import google_sync
        person = {
            'resourceName': 'people/c1',
            'names': [{'displayName': 'Acme Inc'}],
            'organizations': [{'name': 'Acme Inc'}],
        }
        google_sync._upsert_person(db, person, 'US', {})
        row = db.execute("SELECT type FROM contacts WHERE name = 'Acme Inc'").fetchone()
        assert row['type'] == 'company'

    def test_person_with_given_name_is_individual(self, db):
        import google_sync
        person = {
            'resourceName': 'people/c2',
            'names': [{'displayName': 'Bob Smith', 'givenName': 'Bob',
                       'familyName': 'Smith'}],
            'organizations': [{'name': 'Acme Inc'}],  # employer, but a person
        }
        google_sync._upsert_person(db, person, 'US', {})
        row = db.execute("SELECT type FROM contacts WHERE name = 'Bob Smith'").fetchone()
        assert row['type'] == 'individual'


class TestMidPaginationPreservesPages:
    def test_error_on_page_two_keeps_page_one(self, app, monkeypatch):
        import google_sync

        monkeypatch.setattr(google_sync, '_load_credentials', lambda config: object())

        calls = {'n': 0}

        class _Exec:
            def __init__(self, fn):
                self._fn = fn

            def execute(self):
                return self._fn()

        class _FakeService:
            def people(self):
                return self

            def connections(self):
                return self

            def list(self, **kwargs):
                calls['n'] += 1

                def _page():
                    if calls['n'] == 1:
                        return {
                            'connections': [{
                                'resourceName': 'people/p1',
                                'names': [{'displayName': 'PageOne Person'}],
                            }],
                            'nextPageToken': 'PAGE2',
                        }
                    raise RuntimeError('transient API failure on page 2')
                return _Exec(_page)

        import googleapiclient.discovery
        monkeypatch.setattr(
            googleapiclient.discovery, 'build',
            lambda *a, **k: _FakeService(),
        )

        with app.app_context():
            conn = get_db()
            synced, error = google_sync.sync_contacts({}, conn, 'US')
            # Page 1 was committed before page 2 failed.
            assert error is not None
            assert synced == 1
            row = conn.execute(
                "SELECT name FROM contacts WHERE name = 'PageOne Person'"
            ).fetchone()
            assert row is not None


class TestSchemaVersioning:
    def test_migrations_recorded(self, app):
        with app.app_context():
            conn = get_db()
            applied = {
                r['filename']
                for r in conn.execute('SELECT filename FROM schema_version')
            }
        assert '001_initial.sql' in applied
        assert '002_add_indexes.sql' in applied

    def test_reinit_is_noop(self, app):
        # Running init_db again must not error or duplicate schema_version rows.
        import db as db_mod
        with app.app_context():
            db_mod.init_db()
            conn = get_db()
            count = conn.execute(
                "SELECT COUNT(*) FROM schema_version WHERE filename = '001_initial.sql'"
            ).fetchone()[0]
        assert count == 1

    def test_002_dedups_before_unique_index(self, tmp_path):
        # Simulate an older database that predates migration 002: it has the
        # custom_fields table (from 001) with case-variant duplicate field
        # names and NO unique index. The migration runner must dedup and create
        # the index without aborting (CL-0008).
        import sqlite3

        db_path = str(tmp_path / 'legacy.db')
        seed = sqlite3.connect(db_path)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'migrations', '001_initial.sql')) as f:
            seed.executescript(f.read())
        seed.execute(
            "INSERT INTO contacts (type, name) VALUES ('individual', 'Alice')"
        )
        cid = seed.execute('SELECT id FROM contacts').fetchone()[0]
        # Two case-variant duplicates of the same field name.
        seed.execute(
            'INSERT INTO custom_fields (contact_id, field_name, field_value) '
            "VALUES (?, 'Nickname', 'Al')", [cid])
        seed.execute(
            'INSERT INTO custom_fields (contact_id, field_name, field_value) '
            "VALUES (?, 'nickname', 'Ally')", [cid])
        seed.commit()
        seed.close()

        # Now run the full app (its init_db) against the seeded legacy DB.
        app = create_app({
            'TESTING': True,
            'DATABASE': db_path,
            'SECRET_KEY': 'test-secret',
            'GOOGLE_CREDENTIALS_DIR': str(tmp_path / 'g'),
            'GOOGLE_CREDENTIALS_FILE': str(tmp_path / 'g' / 'c.json'),
            'GOOGLE_TOKEN_FILE': str(tmp_path / 'g' / 't.json'),
        })
        with app.app_context():
            conn = get_db()
            # Exactly one nickname row survived the dedup.
            n = conn.execute(
                'SELECT COUNT(*) FROM custom_fields WHERE contact_id = ?', [cid]
            ).fetchone()[0]
            assert n == 1
            # The unique index now exists.
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_cf_unique'"
            ).fetchone()
            assert idx is not None


class TestTightenedCSP:
    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def test_style_src_has_no_unsafe_inline(self, client):
        resp = client.get('/contacts')
        csp = resp.headers.get('Content-Security-Policy', '')
        assert "style-src 'self'" in csp
        assert 'unsafe-inline' not in csp

    def test_pages_render_without_inline_styles(self, client):
        # Every page that used to carry inline style= attributes must still
        # render 200 and contain no `style="` attribute in the output.
        client.post('/contacts', data={
            '_csrf_token': _csrf(client),
            'type': 'individual', 'name': 'Zoe', 'phone': '+1 202-555-0111',
        })
        # a second Zoe to make the duplicates page show a group
        client.post('/contacts', data={
            '_csrf_token': _csrf(client),
            'type': 'individual', 'name': 'Zoe',
        })
        for path in ('/contacts', '/contacts/new', '/contacts/duplicates',
                     '/sync', '/settings'):
            resp = client.get(path)
            assert resp.status_code == 200, f'{path} -> {resp.status_code}'
            assert b'style="' not in resp.data, f'{path} still has an inline style'


def _csrf(client) -> str:
    client.get('/contacts/new')
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


class TestEnsurePrivateDir:
    def test_creates_dir_0700(self, tmp_path):
        import config
        target = tmp_path / 'cfg'
        config.ensure_private_dir(str(target))
        assert target.is_dir()
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700, f'expected 0700, got {oct(mode)}'

    def test_tightens_existing_loose_dir(self, tmp_path):
        import config
        target = tmp_path / 'cfg'
        target.mkdir(mode=0o755)
        config.ensure_private_dir(str(target))
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700, f'expected 0700, got {oct(mode)}'


class TestSyncPhotos:
    """Google-sync photo download + storage (CL-0026)."""

    _PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40

    def _person(self, url, default=False):
        return {
            'resourceName': 'people/p1',
            'names': [{'displayName': 'Photo Person', 'givenName': 'Photo'}],
            'photos': [{'url': url, 'default': default}],
        }

    def _cid(self, db):
        return db.execute(
            "SELECT id FROM contacts WHERE name = 'Photo Person'"
        ).fetchone()['id']

    def test_real_photo_stored(self, app, db, monkeypatch):
        import google_sync
        import models
        monkeypatch.setattr(google_sync, '_fetch_photo_bytes', lambda url: self._PNG)
        person = self._person('https://lh3.googleusercontent.com/abc')
        google_sync._upsert_person(db, person, 'US', app.config)
        cid = self._cid(db)
        assert models.get_contact_photo_ext(db, cid) == 'png'
        assert os.path.exists(os.path.join(app.config['PHOTOS_DIR'], f'{cid}.png'))

    def test_default_photo_not_stored(self, app, db, monkeypatch):
        import google_sync
        import models
        monkeypatch.setattr(google_sync, '_fetch_photo_bytes', lambda url: self._PNG)
        person = self._person('https://lh3.googleusercontent.com/abc', default=True)
        google_sync._upsert_person(db, person, 'US', app.config)
        assert models.get_contact_photo_ext(db, self._cid(db)) is None

    def test_non_google_host_skipped(self, app, db, monkeypatch):
        import google_sync
        import models
        # Even if the fetch would succeed, a non-googleusercontent host is skipped.
        monkeypatch.setattr(google_sync, '_fetch_photo_bytes', lambda url: self._PNG)
        person = self._person('https://evil.example.com/abc.png')
        google_sync._upsert_person(db, person, 'US', app.config)
        assert models.get_contact_photo_ext(db, self._cid(db)) is None

    def test_download_error_leaves_contact_photoless(self, app, db, monkeypatch):
        import google_sync
        import models

        def boom(url):
            raise OSError('network down')

        monkeypatch.setattr(google_sync, '_fetch_photo_bytes', boom)
        person = self._person('https://lh3.googleusercontent.com/abc')
        # Import must still succeed; the contact is stored without a photo.
        assert google_sync._upsert_person(db, person, 'US', app.config) is True
        assert models.get_contact_photo_ext(db, self._cid(db)) is None


# --- Two-way sync: OAuth scope upgrade & re-consent (CL-0033) ---------------

_READONLY = ['https://www.googleapis.com/auth/contacts.readonly']
_WRITE = ['https://www.googleapis.com/auth/contacts']


def _write_token(path, scopes):
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump({
            'token': 'fake-access-token', 'refresh_token': 'r',
            'client_id': 'c', 'client_secret': 's',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'scopes': scopes,
            'expiry': '2099-01-01T00:00:00Z',  # far future -> valid, no refresh
        }, f)


class TestReconsent:
    def test_no_token_neither_authenticated_nor_reconsent(self, app):
        import google_sync
        cfg = app.config
        assert google_sync.is_authenticated(cfg) is False
        assert google_sync.needs_reconsent(cfg) is False

    def test_legacy_readonly_token_needs_reconsent(self, app):
        import google_sync
        cfg = app.config
        _write_token(cfg['GOOGLE_TOKEN_FILE'], _READONLY)
        # Detected via the token file's OWN scopes, even though the app now
        # requests the write scope.
        assert google_sync.is_authenticated(cfg) is False
        assert google_sync.needs_reconsent(cfg) is True

    def test_write_scope_token_authenticated(self, app):
        import google_sync
        cfg = app.config
        _write_token(cfg['GOOGLE_TOKEN_FILE'], _WRITE)
        assert google_sync.needs_reconsent(cfg) is False
        assert google_sync.is_authenticated(cfg) is True

    def test_token_missing_scopes_key_needs_reconsent(self, app):
        import json
        import google_sync
        cfg = app.config
        path = cfg['GOOGLE_TOKEN_FILE']
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump({'token': 't', 'refresh_token': 'r', 'client_id': 'c',
                       'client_secret': 's',
                       'token_uri': 'https://oauth2.googleapis.com/token'}, f)
        assert google_sync.needs_reconsent(cfg) is True

    def test_scopes_single_source(self):
        import google_auth
        import google_sync
        assert google_auth.SCOPES is google_sync.SCOPES
        assert google_sync.SCOPES == _WRITE

    def test_sync_page_prompts_reconnect_for_legacy_token(self, app):
        # A legacy read-only token makes /sync show the reconnect prompt, not the
        # ordinary first-time authorise prompt.
        _write_token(app.config['GOOGLE_TOKEN_FILE'], _READONLY)
        # Credentials file must exist so the page passes the "setup" gate.
        os.makedirs(app.config['GOOGLE_CREDENTIALS_DIR'], exist_ok=True)
        with open(app.config['GOOGLE_CREDENTIALS_FILE'], 'w') as f:
            f.write('{}')
        resp = app.test_client().get('/sync')
        assert resp.status_code == 200
        assert b'Reconnect to Google' in resp.data
        assert b'new permission' in resp.data
