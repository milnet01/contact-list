"""Two-way Google sync — push phase (CL-0033).

Mocks the Google People API client at the external boundary (DESIGN.md §11),
following the _FakeService/monkeypatch pattern in test_hardening.py.
"""

from __future__ import annotations

import pytest

import google_sync
import models
from app import create_app
from db import get_db


@pytest.fixture()
def app(tmp_path):
    gcreds = tmp_path / 'g'
    app = create_app({
        'TESTING': True,
        'DATABASE': str(tmp_path / 'test.db'),
        'SECRET_KEY': 'test',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })
    yield app


@pytest.fixture()
def db(app):
    with app.app_context():
        yield get_db()


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _FakeService:
    """One object standing in for people().connections()/createContact()/get()/
    updateContact()/deleteContact(). people()/connections() return self."""

    def __init__(self, pull_pages=None, get_responses=None):
        self.pull_pages = pull_pages or [{'connections': [], 'nextSyncToken': 'TOK'}]
        self.get_responses = get_responses or {}
        self.created: list = []
        self.updated: list = []
        self.deleted: list = []
        self._page = 0

    def people(self):
        return self

    def connections(self):
        return self

    def list(self, **kwargs):
        def run():
            page = self.pull_pages[min(self._page, len(self.pull_pages) - 1)]
            self._page += 1
            return page
        return _Exec(run)

    def createContact(self, body=None):
        def run():
            self.created.append(body)
            n = len(self.created)
            return {'resourceName': f'people/new{n}', 'etag': f'etag-new{n}'}
        return _Exec(run)

    def get(self, resourceName=None, personFields=None):
        def run():
            return self.get_responses.get(
                resourceName, {'resourceName': resourceName, 'etag': 'g-etag'})
        return _Exec(run)

    def updateContact(self, resourceName=None, updatePersonFields=None, body=None):
        def run():
            self.updated.append((resourceName, updatePersonFields, body))
            return {'resourceName': resourceName, 'etag': 'etag-upd'}
        return _Exec(run)

    def deleteContact(self, resourceName=None):
        def run():
            self.deleted.append(resourceName)
            return {}
        return _Exec(run)


def _run_sync(app, db, service, monkeypatch):
    monkeypatch.setattr(google_sync, '_load_credentials', lambda config: object())
    import googleapiclient.discovery
    monkeypatch.setattr(googleapiclient.discovery, 'build', lambda *a, **k: service)
    with app.app_context():
        return google_sync.sync_contacts(app.config, db, 'US')


def _set_prev_sync(db, ts):
    db.execute(
        'INSERT INTO sync_state (id, sync_token, last_synced_at) VALUES (1, NULL, ?) '
        'ON CONFLICT(id) DO UPDATE SET last_synced_at = excluded.last_synced_at',
        [ts])
    db.commit()


def _link(db, cid, google_id, etag='old-etag'):
    db.execute('UPDATE contacts SET google_id=?, etag=? WHERE id=?',
               [google_id, etag, cid])
    db.commit()


def _make_dirty_edit(db, cid, when='2099-01-01T00:00:00Z'):
    """Force edited_at to a value after prev_sync so the contact is dirty."""
    db.execute("UPDATE contact_edits SET edited_at=? WHERE contact_id=?", [when, cid])
    db.commit()


class TestPushCreate:
    def test_local_only_contact_is_created_on_google(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'New Nancy', 'nancy@x.com')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        service = _FakeService()
        result = _run_sync(app, db, service, monkeypatch)
        assert result.error is None
        assert result.created == 1
        assert len(service.created) == 1
        # google_id + etag persisted so a re-run won't re-create it.
        row = db.execute('SELECT google_id, etag FROM contacts WHERE id=?', [cid]).fetchone()
        assert row['google_id'] == 'people/new1'
        assert row['etag'] == 'etag-new1'

    def test_second_sync_does_not_recreate(self, app, db, monkeypatch):
        models.create_contact(db, 'individual', 'New Nancy')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _run_sync(app, db, _FakeService(), monkeypatch)
        service2 = _FakeService()
        result = _run_sync(app, db, service2, monkeypatch)
        assert result.created == 0
        assert service2.created == []


class TestPushUpdate:
    def test_edited_linked_contact_is_updated(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Linked Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        # Google unchanged since prev_sync (updateTime BEFORE prev_sync) -> no
        # conflict, plain push.
        service = _FakeService(get_responses={'people/lee': {
            'resourceName': 'people/lee', 'etag': 'fresh-etag',
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})
        result = _run_sync(app, db, service, monkeypatch)
        assert result.updated == 1
        assert len(service.updated) == 1
        res_name, fields, body = service.updated[0]
        assert res_name == 'people/lee'
        assert body['etag'] == 'fresh-etag'  # carries the fresh get etag

    def test_multi_value_phone_preserved(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Multi Mo', phone='+1 202-555-0100')
        _link(db, cid, 'people/mo')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        # Google contact has TWO phones; our edit must keep the second.
        service = _FakeService(get_responses={'people/mo': {
            'resourceName': 'people/mo', 'etag': 'e',
            'phoneNumbers': [{'value': 'OLD-PRIMARY'}, {'value': 'SECOND-KEEP'}],
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2020-06-01T00:00:00Z'}]},
        }})
        _run_sync(app, db, service, monkeypatch)
        _res, _fields, body = service.updated[0]
        values = [p['value'] for p in body['phoneNumbers']]
        assert 'SECOND-KEEP' in values          # secondary preserved (INV-2)
        assert values[0] == '+1 202-555-0100'    # our value at index 0


class TestConflictLWW:
    def _setup(self, db, google_update_time, local_edit_time):
        cid = models.create_contact(db, 'individual', 'Connie', 'connie@x.com')
        _link(db, cid, 'people/connie')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid, local_edit_time)
        service = _FakeService(get_responses={'people/connie': {
            'resourceName': 'people/connie', 'etag': 'e',
            'names': [{'displayName': 'Google Connie'}],
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': google_update_time}]},
        }})
        return cid, service

    def test_google_newer_wins(self, app, db, monkeypatch):
        # Google edited 2021, local edited 2020-06 -> both changed since prev_sync
        # (2020-01), Google newer -> apply Google locally, no updateContact.
        cid, service = self._setup(db, '2021-01-01T00:00:00Z', '2020-06-01T00:00:00Z')
        result = _run_sync(app, db, service, monkeypatch)
        assert result.conflicts_google == 1
        assert service.updated == []
        name = db.execute('SELECT name FROM contacts WHERE id=?', [cid]).fetchone()['name']
        assert name == 'Google Connie'  # local overwritten with Google's newer copy

    def test_local_newer_wins(self, app, db, monkeypatch):
        # Google edited 2020-06, local edited 2021 -> local newer -> push.
        cid, service = self._setup(db, '2020-06-01T00:00:00Z', '2021-01-01T00:00:00Z')
        result = _run_sync(app, db, service, monkeypatch)
        assert result.conflicts_local == 1
        assert len(service.updated) == 1

    def test_fractional_seconds_do_not_misorder(self, app, db, monkeypatch):
        # Google time has fractional seconds and is clearly newer than local.
        cid, service = self._setup(db, '2021-01-01T00:00:00.500000Z', '2020-06-01T00:00:00Z')
        result = _run_sync(app, db, service, monkeypatch)
        assert result.conflicts_google == 1


class TestMissingUpdateTime:
    def test_absent_update_time_counts_and_does_not_push(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Timeless Tom', 'tom@x.com')
        _link(db, cid, 'people/tom')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        service = _FakeService(get_responses={'people/tom': {
            'resourceName': 'people/tom', 'etag': 'e',
            'metadata': {'sources': [{'type': 'CONTACT'}]},  # no updateTime
        }})
        result = _run_sync(app, db, service, monkeypatch)
        assert result.push_no_time == 1
        assert service.updated == []


class TestNoDeletions:
    def test_delete_is_never_called(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Keep Ken')
        _link(db, cid, 'people/ken')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        # Delete the contact locally after linking.
        models.delete_contact(db, cid)
        service = _FakeService()
        _run_sync(app, db, service, monkeypatch)
        assert service.deleted == []


class TestFinalise:
    def test_last_synced_advances_without_new_token(self, app, db, monkeypatch):
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        # A pull page with NO nextSyncToken must still advance last_synced_at.
        service = _FakeService(pull_pages=[{'connections': []}])
        _run_sync(app, db, service, monkeypatch)
        ts = db.execute('SELECT last_synced_at FROM sync_state WHERE id=1').fetchone()[0]
        assert ts != '2020-01-01T00:00:00Z'


class TestFirstSyncNoUpdates:
    def test_null_prev_sync_pushes_creates_only(self, app, db, monkeypatch):
        # Never synced (no sync_state): a linked+edited contact is NOT push-updated
        # (nothing has diverged from a baseline yet); local-only IS created.
        linked = models.create_contact(db, 'individual', 'Prelinked', 'p@x.com')
        _link(db, linked, 'people/pre')
        _make_dirty_edit(db, linked)
        models.create_contact(db, 'individual', 'Fresh Local')
        service = _FakeService()
        result = _run_sync(app, db, service, monkeypatch)
        assert result.updated == 0 and result.conflicts_local == 0
        assert service.updated == []
        assert result.created == 1  # only the local-only contact


class TestDirtyDefer:
    def test_pull_does_not_overwrite_a_dirty_local_edit(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Local Name', 'x@x.com')
        _link(db, cid, 'people/dd')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid, '2021-01-01T00:00:00Z')
        # The delta pull returns this same contact with a DIFFERENT Google name;
        # because it is locally dirty it must be DEFERRED (not overwritten), so the
        # push still sees the local name. Google changed 2020-06 (< local 2021) ->
        # local wins.
        pull = [{'connections': [{
            'resourceName': 'people/dd',
            'names': [{'displayName': 'Google Name'}],
        }], 'nextSyncToken': 'TOK'}]
        service = _FakeService(pull_pages=pull, get_responses={'people/dd': {
            'resourceName': 'people/dd', 'etag': 'e',
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2020-06-01T00:00:00Z'}]},
        }})
        result = _run_sync(app, db, service, monkeypatch)
        assert result.conflicts_local == 1
        _res, _fields, body = service.updated[0]
        assert body['names'][0]['unstructuredName'] == 'Local Name'
