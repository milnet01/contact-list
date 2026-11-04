"""Two-way Google sync — push phase (CL-0033).

Mocks the Google People API client at the external boundary (DESIGN.md §11),
following the _FakeService/monkeypatch pattern in test_hardening.py.
"""

from __future__ import annotations

from typing import ClassVar

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
    def __init__(self, fn, retries_seen=None):
        self._fn = fn
        self._retries_seen = retries_seen

    def execute(self, num_retries=0):
        if self._retries_seen is not None:
            self._retries_seen.append(num_retries)
        return self._fn()


# The body the People API sends when the token lacks the write scope.
_SCOPE_DENIED_BODY = (
    b'{"error": {"code": 403, "message": "Request had insufficient '
    b'authentication scopes.", "errors": [{"message": "Insufficient Permission", '
    b'"domain": "global", "reason": "insufficientPermissions"}], '
    b'"status": "PERMISSION_DENIED", "details": [{"@type": '
    b'"type.googleapis.com/google.rpc.ErrorInfo", '
    b'"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}}')


class _FakeService:
    """One object standing in for people().connections()/createContact()/get()/
    updateContact()/deleteContact(). people()/connections() return self."""

    def __init__(self, pull_pages=None, get_responses=None):
        self.pull_pages = pull_pages or [{'connections': [], 'nextSyncToken': 'TOK'}]
        self.get_responses = get_responses or {}
        self.created: list = []
        self.updated: list = []
        self.deleted: list = []
        self.retries_seen: list = []  # num_retries of every execute() (CL-0070)
        self.got: list = []  # resourceNames passed to get()
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
        return _Exec(run, self.retries_seen)

    def createContact(self, body=None):
        def run():
            self.created.append(body)
            n = len(self.created)
            return {'resourceName': f'people/new{n}', 'etag': f'etag-new{n}'}
        return _Exec(run, self.retries_seen)

    def get(self, resourceName=None, personFields=None):
        def run():
            self.got.append(resourceName)
            return self.get_responses.get(
                resourceName, {'resourceName': resourceName, 'etag': 'g-etag'})
        return _Exec(run, self.retries_seen)

    def updateContact(self, resourceName=None, updatePersonFields=None, body=None):
        def run():
            self.updated.append((resourceName, updatePersonFields, body))
            return {'resourceName': resourceName, 'etag': 'etag-upd'}
        return _Exec(run, self.retries_seen)

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


class TestRateLimitRetries:
    """CL-0070: every People API call asks the client library to retry, so a
    429 during the one-time bulk create backs off instead of skipping contacts."""

    def test_every_api_call_requests_retries(self, app, db, monkeypatch):
        models.create_contact(db, 'individual', 'New Nancy')
        cid = models.create_contact(db, 'individual', 'Linked Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        service = _FakeService(get_responses={'people/lee': {
            'resourceName': 'people/lee', 'etag': 'fresh-etag',
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})
        result = _run_sync(app, db, service, monkeypatch)
        assert (result.created, result.updated) == (1, 1)
        # list, createContact, get, updateContact: all four call sites.
        assert len(service.retries_seen) == 4
        assert set(service.retries_seen) == {google_sync._API_RETRIES}
        assert google_sync._API_RETRIES > 0

    def test_a_rate_limit_403_is_not_reported_as_lost_scope(self):
        class _Resp:
            status = 403

        class _Err(Exception):
            resp = _Resp()
            content = (b'{"error": {"errors": '
                       b'[{"reason": "rateLimitExceeded"}]}}')

        class _ScopeErr(Exception):
            resp = _Resp()
            content = _SCOPE_DENIED_BODY

        assert google_sync._is_write_scope_denied(_Err()) is False
        assert google_sync._is_write_scope_denied(_ScopeErr()) is True

    @pytest.mark.parametrize('body', [
        # CL-0117: a daily quota refusal is not a lost write scope.
        b'{"error": {"code": 403, "status": "PERMISSION_DENIED", "errors": '
        b'[{"reason": "dailyLimitExceeded"}]}}',
        # CL-0117: a read refused for another reason (no scope reason given).
        b'{"error": {"code": 403, "message": "The caller does not have '
        b'permission", "status": "PERMISSION_DENIED"}}',
    ])
    def test_a_403_without_a_scope_reason_is_not_lost_scope(self, body):
        class _Resp:
            status = 403

        class _Err(Exception):
            resp = _Resp()
            content = body

        assert google_sync._is_write_scope_denied(_Err()) is False


class TestTombstoneForAnEditedContact:
    """CL-0070, INV-9: a delete tombstone is checked before the deferral."""

    _TOMBSTONE: ClassVar[dict] = {'connections': [{'resourceName': 'people/lee',
                                   'metadata': {'deleted': True}}],
                  'nextSyncToken': 'TOK'}

    def test_edited_contact_is_kept_unlinked_and_recreated(
            self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Linked Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        service = _FakeService(pull_pages=[self._TOMBSTONE])
        result = _run_sync(app, db, service, monkeypatch)
        assert result.error is None
        row = db.execute('SELECT name, email, google_id, etag FROM contacts '
                         'WHERE id=?', [cid]).fetchone()
        assert row is not None, 'the locally-edited contact was deleted'
        assert (row['name'], row['email']) == ('Linked Lee', 'lee@x.com')
        # Re-created on Google in the same run, never updated at its old address.
        assert result.created == 1 and len(service.created) == 1
        assert service.updated == [] and 'people/lee' not in service.got
        assert (row['google_id'], row['etag']) == ('people/new1', 'etag-new1')

    def test_unedited_contact_is_still_deleted(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Linked Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2099-06-01T00:00:00Z')  # after the edit: not dirty
        service = _FakeService(pull_pages=[self._TOMBSTONE])
        result = _run_sync(app, db, service, monkeypatch)
        assert result.error is None
        assert db.execute('SELECT 1 FROM contacts WHERE id=?', [cid]).fetchone() is None
        assert service.created == []


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
        res_name, _fields, body = service.updated[0]
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
        _cid, service = self._setup(db, '2020-06-01T00:00:00Z', '2021-01-01T00:00:00Z')
        result = _run_sync(app, db, service, monkeypatch)
        assert result.conflicts_local == 1
        assert len(service.updated) == 1

    def test_fractional_seconds_do_not_misorder(self, app, db, monkeypatch):
        # Google time has fractional seconds and is clearly newer than local.
        _cid, service = self._setup(db, '2021-01-01T00:00:00.500000Z', '2020-06-01T00:00:00Z')
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


class TestExpiredSyncTokenSelfHeal:
    """An expired sync token clears ONLY sync_token, preserving last_synced_at.

    Why this exists: the self-heal path used to `DELETE FROM sync_state WHERE id
    = 1`, wiping last_synced_at along with the token. If the restarted full pull
    then failed on a later page, Step 3 (which advances last_synced_at) never
    ran, last_synced_at stayed NULL, and the next sync computed an EMPTY dirty
    set -- silently disabling the pull's deferral and letting Google overwrite
    unpushed local edits. The retry is made to fail here too, so Step 3 never
    runs and the only source of last_synced_at's value is whatever survived the
    self-heal -- proving it was preserved rather than merely re-set later.
    """

    class _ExpiredThenBrokenService:
        """list() raises the expired-sync-token error when called with a
        syncToken; the retry (no syncToken) raises a plain failure, so the sync
        never reaches Step 3."""

        def __init__(self):
            self.calls: list[dict] = []

        def people(self):
            return self

        def connections(self):
            return self

        def list(self, **kwargs):
            self.calls.append(kwargs)

            def run():
                if 'syncToken' in kwargs:
                    from googleapiclient.errors import HttpError

                    class _Resp:
                        status = 400
                        reason = 'Bad Request'

                    raise HttpError(
                        _Resp(),
                        b'{"error": {"status": "INVALID_ARGUMENT", "message": '
                        b'"Sync token is expired. Retry with an empty token. '
                        b'Reason: EXPIRED_SYNC_TOKEN"}}',
                    )
                raise RuntimeError('network died mid-resync')
            return _Exec(run)

    def test_last_synced_at_survives_a_self_heal_whose_retry_then_fails(
        self, app, db, monkeypatch
    ):
        db.execute(
            'INSERT INTO sync_state (id, sync_token, last_synced_at) '
            "VALUES (1, 'STALE-TOKEN', '2020-01-01T00:00:00Z')"
        )
        db.commit()
        service = self._ExpiredThenBrokenService()
        result = _run_sync(app, db, service, monkeypatch)
        assert result.error is not None  # the retry's RuntimeError surfaced
        # The retry was made with no syncToken (a clean full resync).
        assert 'syncToken' not in service.calls[-1]
        row = db.execute(
            'SELECT sync_token, last_synced_at FROM sync_state WHERE id = 1'
        ).fetchone()
        assert row['sync_token'] is None            # cleared by the self-heal
        assert row['last_synced_at'] == '2020-01-01T00:00:00Z'  # preserved, not wiped


class TestFieldClear:
    """CL-0064 / INV-8: clearing a managed field locally reaches Google.

    Before this, an empty local value was omitted from both the body and
    updatePersonFields, so Google kept its copy and put it back. These lock
    both halves: the three fields a clear IS pushed on, and the four it is
    deliberately not, where an empty local value does not imply a user clear.
    """

    def _cleared_phone(self, db, google_phones):
        cid = models.create_contact(
            db, 'individual', 'Clara', phone='+1 202-555-0100')
        models.update_contact(db, cid, 'individual', 'Clara', phone=None)
        _link(db, cid, 'people/clara')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        return _FakeService(get_responses={'people/clara': {
            'resourceName': 'people/clara', 'etag': 'e',
            'phoneNumbers': google_phones,
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})

    def test_clearing_a_phone_drops_googles_primary_and_keeps_the_rest(
        self, app, db, monkeypatch
    ):
        service = self._cleared_phone(
            db, [{'value': 'OLD-PRIMARY'}, {'value': 'SECOND-KEEP'}])
        _run_sync(app, db, service, monkeypatch)
        _res, fields, body = service.updated[0]
        assert 'phoneNumbers' in fields, 'a cleared field must be listed, or Google never hears it'
        assert [p['value'] for p in body['phoneNumbers']] == ['SECOND-KEEP']

    def test_clearing_the_only_phone_sends_an_empty_list(
        self, app, db, monkeypatch
    ):
        service = self._cleared_phone(db, [{'value': 'OLD-PRIMARY'}])
        _run_sync(app, db, service, monkeypatch)
        _res, fields, body = service.updated[0]
        assert 'phoneNumbers' in fields
        assert body['phoneNumbers'] == []

    def test_a_field_empty_on_both_sides_is_omitted(self, app, db, monkeypatch):
        # Nothing to clear. Listing it would write an empty list over an empty
        # list, which is a pointless write against the etag.
        service = self._cleared_phone(db, [])
        _run_sync(app, db, service, monkeypatch)
        _res, fields, body = service.updated[0]
        assert 'phoneNumbers' not in fields
        assert 'phoneNumbers' not in body

    def test_a_company_contacts_organization_is_never_cleared(
        self, app, db, monkeypatch
    ):
        # §6: the app does not manage organizations for a type='company'
        # contact -- its org name lives in `name`. So the permanently-empty
        # local value is NOT a clear, and pushing one would wipe Google's entry.
        cid = models.create_contact(db, 'company', 'Acme Ltd')
        _link(db, cid, 'people/acme')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        service = _FakeService(get_responses={'people/acme': {
            'resourceName': 'people/acme', 'etag': 'e',
            'organizations': [{'name': 'KEEP-ME'}],
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})
        _run_sync(app, db, service, monkeypatch)
        _res, fields, body = service.updated[0]
        assert 'organizations' not in fields
        assert 'organizations' not in body

    def test_a_birthday_the_import_never_stored_is_never_cleared(
        self, app, db, monkeypatch
    ):
        # The import drops a Google birthday with no month+day, so an absent
        # local birthday says nothing about what the user did.
        cid = models.create_contact(db, 'individual', 'Bea')
        _link(db, cid, 'people/bea')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid)
        service = _FakeService(get_responses={'people/bea': {
            'resourceName': 'people/bea', 'etag': 'e',
            'birthdays': [{'date': {'year': 1990}}],
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})
        _run_sync(app, db, service, monkeypatch)
        _res, fields, body = service.updated[0]
        assert 'birthdays' not in fields
        assert 'birthdays' not in body


class TestPullReplacesDifferentlyCasedLocalFields:
    """The pull owns the birthday, address and organization custom fields, and
    the push already reads them case-insensitively (CL-0113)."""

    def test_pull_replaces_a_capitalised_birthday_field(self, app, db, monkeypatch):
        cid = models.create_contact(
            db, 'individual', 'Bea', custom_fields=[('Birthday', '1980-01-01')])
        _link(db, cid, 'people/bea')
        pull = [{'connections': [{
            'resourceName': 'people/bea',
            'names': [{'displayName': 'Bea'}],
            'birthdays': [{'date': {'year': 1990, 'month': 2, 'day': 3}}],
        }], 'nextSyncToken': 'TOK'}]
        result = _run_sync(app, db, _FakeService(pull_pages=pull), monkeypatch)
        assert result.pulled == 1
        rows = [(r['field_name'].lower(), r['field_value'])
                for r in models.get_custom_fields(db, cid)]
        assert rows == [('birthday', '1990-02-03')]


class TestBaselineOnlyAdvancesOnACleanPush:
    """Spec 2026-07-02-two-way-google-sync.md, partial run: last_synced_at moves
    only on a clean finish, so a failed push is retried next sync."""

    def _failing_update_service(self):
        class _Failing(_FakeService):
            def updateContact(self, resourceName=None, updatePersonFields=None, body=None):
                def run():
                    raise RuntimeError('boom')
                return _Exec(run, self.retries_seen)
        return _Failing(get_responses={'people/lee': {
            'resourceName': 'people/lee', 'etag': 'e',
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})

    def test_a_skipped_push_keeps_the_old_baseline(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid, '2021-01-01T00:00:00Z')
        result = _run_sync(app, db, self._failing_update_service(), monkeypatch)
        assert result.skipped == 1
        ts, token = db.execute(
            'SELECT last_synced_at, sync_token FROM sync_state WHERE id=1').fetchone()
        assert ts == '2020-01-01T00:00:00Z'
        assert token == 'TOK'  # the pull committed, so its token still moves

    def test_the_retry_pushes_the_edit_once_it_works(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid, '2021-01-01T00:00:00Z')
        _run_sync(app, db, self._failing_update_service(), monkeypatch)
        service = _FakeService(get_responses=self._failing_update_service().get_responses)
        result = _run_sync(app, db, service, monkeypatch)
        assert result.updated == 1 and len(service.updated) == 1


class _Denied(Exception):
    """Looks like a 403 write-scope refusal to google_sync's duck-typing."""
    status_code = 403
    content = _SCOPE_DENIED_BODY


def _baseline(db):
    row = db.execute('SELECT last_synced_at FROM sync_state WHERE id=1').fetchone()
    return row[0] if row else None


class TestBaselineHeldOnlyForUnpushedLinkedEdits:
    """The baseline is held only when an edit to a linked contact is left unpushed.
    Local-only creates are recomputed every sync, so they never hold it."""

    @staticmethod
    def _create_refusing_service(exc):
        class _S(_FakeService):
            def createContact(self, body=None):
                def run():
                    raise exc
                return _Exec(run, self.retries_seen)
        return _S()

    def test_first_sync_with_a_refused_create_sets_the_baseline(
            self, app, db, monkeypatch):
        models.create_contact(db, 'individual', 'Local', 'l@x.com')
        service = self._create_refusing_service(RuntimeError('refused'))
        result = _run_sync(app, db, service, monkeypatch)
        assert result.skipped == 1
        assert _baseline(db) is not None

    def test_refused_create_with_an_existing_baseline_advances(
            self, app, db, monkeypatch):
        models.create_contact(db, 'individual', 'Local', 'l@x.com')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        service = self._create_refusing_service(RuntimeError('refused'))
        result = _run_sync(app, db, service, monkeypatch)
        assert result.skipped == 1
        assert _baseline(db) != '2020-01-01T00:00:00Z'

    def test_scope_refusal_during_creates_with_dirty_linked_holds(
            self, app, db, monkeypatch):
        models.create_contact(db, 'individual', 'Local', 'l@x.com')
        cid = models.create_contact(db, 'individual', 'Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid, '2021-01-01T00:00:00Z')
        service = self._create_refusing_service(_Denied())
        result = _run_sync(app, db, service, monkeypatch)
        assert result.error is not None
        assert _baseline(db) == '2020-01-01T00:00:00Z'

    def test_scope_refusal_with_nothing_dirty_linked_advances(
            self, app, db, monkeypatch):
        models.create_contact(db, 'individual', 'Local', 'l@x.com')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        service = self._create_refusing_service(_Denied())
        result = _run_sync(app, db, service, monkeypatch)
        assert result.error is not None
        assert _baseline(db) != '2020-01-01T00:00:00Z'

    def test_a_clean_run_advances(self, app, db, monkeypatch):
        cid = models.create_contact(db, 'individual', 'Lee', 'lee@x.com')
        _link(db, cid, 'people/lee')
        _set_prev_sync(db, '2020-01-01T00:00:00Z')
        _make_dirty_edit(db, cid, '2021-01-01T00:00:00Z')
        service = _FakeService(get_responses={'people/lee': {
            'resourceName': 'people/lee', 'etag': 'e',
            'metadata': {'sources': [{'type': 'CONTACT',
                                      'updateTime': '2019-06-01T00:00:00Z'}]},
        }})
        result = _run_sync(app, db, service, monkeypatch)
        assert result.updated == 1
        assert _baseline(db) != '2020-01-01T00:00:00Z'


class TestSyncFailedMessageShowsWhatWasDone:
    """CL-0116: a sync that stops part-way still reports what it committed."""

    def _start(self, app, monkeypatch, result):
        monkeypatch.setattr(google_sync, 'sync_contacts', lambda *a: result)
        client = app.test_client()
        client.get('/contacts/new')  # a page with a form issues the token
        with client.session_transaction() as sess:
            token = sess['_csrf_token']
        client.post('/sync/start', data={'_csrf_token': token})
        with client.session_transaction() as sess:
            return sess['_flashes']

    def test_counts_before_the_error_are_shown(self, app, monkeypatch):
        result = google_sync.SyncResult(
            pulled=12, created=3, error=google_sync._SCOPE_DENIED_MESSAGE)
        flashes = self._start(app, monkeypatch, result)
        assert flashes == [('error',
                            'Sync failed: Google needs the write permission — '
                            'reconnect. Before it stopped: 12 imported from '
                            'Google, 3 created on Google.')]

    def test_an_error_with_nothing_done_says_only_the_error(self, app, monkeypatch):
        result = google_sync.SyncResult(error='Not authenticated with Google.')
        flashes = self._start(app, monkeypatch, result)
        assert flashes == [('error', 'Sync failed: Not authenticated with Google.')]
