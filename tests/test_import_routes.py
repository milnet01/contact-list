"""End-to-end route tests for import, vCard export, and merge
(CL-0022, CL-0023, CL-0024)."""

from __future__ import annotations

import io

import pytest

import models
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
def client(app):
    return app.test_client()


def _csrf(client) -> str:
    client.get('/contacts/new')
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


def _upload(csv_bytes: bytes, filename: str = 'contacts.csv'):
    return {'file': (io.BytesIO(csv_bytes), filename)}


class TestImportUpload:
    def test_get_shows_form(self, client):
        resp = client.get('/contacts/import')
        assert resp.status_code == 200
        assert b'Import' in resp.data

    def test_post_csv_shows_mapping(self, client):
        token = _csrf(client)
        data = _upload(b'Name,Email\nAlice,a@x.com\n')
        data['_csrf_token'] = token
        resp = client.post('/contacts/import', data=data,
                           content_type='multipart/form-data')
        assert resp.status_code == 200
        assert b'map_0' in resp.data     # a mapping select per column
        assert b'csv_text' in resp.data  # carried CSV
        assert b'Alice' in resp.data     # preview

    def test_missing_csrf_rejected(self, client):
        resp = client.post('/contacts/import', data=_upload(b'Name\nAlice\n'),
                           content_type='multipart/form-data')
        assert resp.status_code == 403

    def test_request_over_max_content_length_413(self, client, app):
        # Flask enforces MAX_CONTENT_LENGTH before the handler runs (production
        # sets 5 MiB via Config; pin a small cap here to exercise the path).
        app.config['MAX_CONTENT_LENGTH'] = 2048
        token = _csrf(client)
        data = _upload(b'Name\n' + b'x' * 4096)
        data['_csrf_token'] = token
        resp = client.post('/contacts/import', data=data,
                           content_type='multipart/form-data')
        assert resp.status_code == 413

    def test_oversize_decoded_body_flashed(self, client):
        token = _csrf(client)
        big = b'Name\n' + (b'x' * (1024 * 1024 + 10))
        data = _upload(big)
        data['_csrf_token'] = token
        resp = client.post('/contacts/import', data=data,
                           content_type='multipart/form-data',
                           follow_redirects=True)
        assert b'too large' in resp.data.lower()


class TestImportApply:
    def test_applies_and_creates(self, client, app):
        token = _csrf(client)
        resp = client.post('/contacts/import/apply', data={
            '_csrf_token': token,
            'csv_text': 'Name,Email\nAlice,a@x.com\nBob,b@x.com\n',
            'default_type': 'individual',
            'map_0': 'name',
            'map_1': 'email',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            contacts, total = models.list_contacts(get_db())
            assert total == 2
            assert {c['name'] for c in contacts} == {'Alice', 'Bob'}

    def test_additive_update_reported(self, client, app):
        with app.app_context():
            models.create_contact(get_db(), 'individual', 'Alice', 'a@x.com')
        token = _csrf(client)
        resp = client.post('/contacts/import/apply', data={
            '_csrf_token': token,
            'csv_text': 'Name,Phone\nAlice,555-1\n',
            'default_type': 'individual',
            'map_0': 'name',
            'map_1': 'phone',
        }, follow_redirects=True)
        assert b'updated' in resp.data.lower()
        with app.app_context():
            c = models.list_contacts(get_db())[0][0]
            assert c['phone'] == '555-1'   # blank filled

    def test_missing_csrf_rejected(self, client):
        resp = client.post('/contacts/import/apply', data={
            'csv_text': 'Name\nAlice\n', 'default_type': 'individual', 'map_0': 'name',
        })
        assert resp.status_code == 403


class TestVcardImportExport:
    def test_import_vcf_immediately(self, client, app):
        token = _csrf(client)
        vcf = b'BEGIN:VCARD\nVERSION:3.0\nFN:Zara\nEMAIL:z@x.com\nEND:VCARD\n'
        data = _upload(vcf, 'contacts.vcf')
        data['_csrf_token'] = token
        resp = client.post('/contacts/import', data=data,
                           content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            contacts, total = models.list_contacts(get_db())
            assert total == 1 and contacts[0]['name'] == 'Zara'

    def test_export_vcard(self, client, app):
        with app.app_context():
            models.create_contact(get_db(), 'individual', 'Alice', 'a@x.com',
                                  custom_fields=[('Nickname', 'Al')])
        resp = client.get('/contacts/export/vcard')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/vcard'
        assert b'BEGIN:VCARD' in resp.data
        assert b'FN:Alice' in resp.data
        assert b'X-CL;X-LABEL=Nickname:Al' in resp.data


class TestMerge:
    def _two_dupes(self, app):
        with app.app_context():
            db = get_db()
            a = models.create_contact(db, 'individual', 'Ann', 'ann@x.com')
            b = models.create_contact(db, 'individual', 'Ann', None, '555-1')
            return a, b

    def test_preview_requires_two(self, client, app):
        a, _ = self._two_dupes(app)
        token = _csrf(client)
        resp = client.post('/contacts/merge', data={
            '_csrf_token': token, 'selected': [str(a)],
        }, follow_redirects=True)
        assert 'at least two'.encode() in resp.data.lower()

    def test_preview_renders_field_choices(self, client, app):
        a, b = self._two_dupes(app)
        token = _csrf(client)
        resp = client.post('/contacts/merge', data={
            '_csrf_token': token, 'selected': [str(a), str(b)],
        })
        assert resp.status_code == 200
        assert b'ann@x.com' in resp.data
        assert b'555-1' in resp.data

    def test_apply_merges(self, client, app):
        a, b = self._two_dupes(app)
        token = _csrf(client)
        resp = client.post('/contacts/merge/apply', data={
            '_csrf_token': token,
            'survivor_id': str(a),
            'loser_id': [str(b)],
            'field_type': 'individual',
            'field_name': 'Ann',
            'field_email': 'ann@x.com',
            'field_phone': '555-1',
            'cf_count': '0',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            db = get_db()
            assert models.get_contact(db, a)['phone'] == '555-1'
            assert models.get_contact(db, b) is None

    def test_apply_missing_csrf_rejected(self, client, app):
        a, b = self._two_dupes(app)
        resp = client.post('/contacts/merge/apply', data={
            'survivor_id': str(a), 'loser_id': [str(b)],
            'field_type': 'individual', 'field_name': 'Ann', 'cf_count': '0',
        })
        assert resp.status_code == 403

    def test_preview_missing_csrf_rejected(self, client, app):
        a, b = self._two_dupes(app)
        resp = client.post('/contacts/merge', data={
            'selected': [str(a), str(b)],
        })
        assert resp.status_code == 403
