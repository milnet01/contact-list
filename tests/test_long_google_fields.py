"""CL-0115: a value over its length cap that the contact already holds (Google
sync writes without the caps) does not block an edit of the other fields.
Decided by the user 2026-11-05: keep Google's value as sent; a later edit
allows an over-long field the user did not change."""

from __future__ import annotations

import pytest

import models
from app import create_app
from db import get_db

LONG_NAME = 'N' * (models.MAX_NAME_LEN + 50)
LONG_NOTES = 'line\n' * (models.MAX_NOTES_LEN // 4)   # over the cap, with newlines


@pytest.fixture()
def app(tmp_path):
    gcreds = tmp_path / 'gcreds'
    return create_app({
        'TESTING': True,
        'DATABASE': str(tmp_path / 'test.db'),
        'SECRET_KEY': 'test-secret',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })


@pytest.fixture()
def long_contact(app) -> int:
    """A contact holding a name and notes over their caps, written the way
    google_sync._upsert_person writes: straight to the table."""
    with app.app_context():
        db = get_db()
        cid = models.create_contact(db, 'individual', 'Short')
        with db:
            db.execute('UPDATE contacts SET name = ?, notes = ? WHERE id = ?',
                       [LONG_NAME, LONG_NOTES, cid])
    return cid


class TestModel:
    def test_an_unchanged_long_value_does_not_block_an_edit(self, app, long_contact):
        with app.app_context():
            db = get_db()
            models.update_contact(db, long_contact, 'individual', LONG_NAME,
                                  'new@x.com', None, LONG_NOTES)
            assert models.get_contact(db, long_contact)['email'] == 'new@x.com'

    def test_a_changed_long_value_is_still_refused(self, app, long_contact):
        with app.app_context():
            with pytest.raises(ValueError, match='Name exceeds'):
                models.update_contact(get_db(), long_contact, 'individual',
                                      LONG_NAME + 'x', None, None, LONG_NOTES)

    def test_a_new_contact_gets_no_such_allowance(self, app):
        with app.app_context():
            with pytest.raises(ValueError, match='Name exceeds'):
                models.create_contact(get_db(), 'individual', LONG_NAME)


class TestEditForm:
    def _post(self, app, cid: int, **fields: str):
        client = app.test_client()
        client.get(f'/contacts/{cid}/edit')
        with client.session_transaction() as sess:
            token = sess.get('_csrf_token', '')
        data = {'_csrf_token': token, 'type': 'individual', **fields}
        return client.post(f'/contacts/{cid}', data=data)

    def test_saves_when_the_long_values_are_untouched(self, app, long_contact):
        # A browser sends a textarea's line breaks as CRLF.
        resp = self._post(app, long_contact, name=LONG_NAME,
                          notes=LONG_NOTES.replace('\n', '\r\n'),
                          email='new@x.com')
        assert resp.status_code == 302
        with app.app_context():
            assert models.get_contact(get_db(), long_contact)['email'] == 'new@x.com'

    def test_refuses_a_long_value_the_user_changed(self, app, long_contact):
        resp = self._post(app, long_contact, name=LONG_NAME + 'x', notes=LONG_NOTES)
        assert resp.status_code == 400
        assert b'Name must be' in resp.data
