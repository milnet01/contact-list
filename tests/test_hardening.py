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
        google_sync._upsert_person(db, person, 'US')
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
        google_sync._upsert_person(db, person, 'US')
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
