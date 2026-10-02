"""End-to-end route tests for import, vCard export, and merge
(CL-0022, CL-0023, CL-0024)."""

from __future__ import annotations

import io
import re

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

    def test_import_reports_skipped_cards_with_no_usable_name(self, client, app):
        # Why this exists: the summary used to hardcode skipped=0, warnings=[],
        # so a card vcard.parse silently dropped (no usable name) vanished from
        # the count entirely -- a 200-card file where 150 were refused rendered
        # as an unqualified "50 created".
        token = _csrf(client)
        vcf = (
            b'BEGIN:VCARD\nVERSION:3.0\nFN:Zara\nEMAIL:z@x.com\nEND:VCARD\n'
            b'BEGIN:VCARD\nVERSION:3.0\nEMAIL:noname@x.com\nEND:VCARD\n'
        )
        data = _upload(vcf, 'contacts.vcf')
        data['_csrf_token'] = token
        resp = client.post('/contacts/import', data=data,
                           content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Skipped' in resp.data
        assert b'no usable name' in resp.data
        with app.app_context():
            contacts, total = models.list_contacts(get_db())
            assert total == 1 and contacts[0]['name'] == 'Zara'


class TestMerge:
    def _two_dupes(self, app):
        with app.app_context():
            db = get_db()
            a = models.create_contact(db, 'individual', 'Ann', 'ann@x.com')
            b = models.create_contact(db, 'individual', 'Ann', None, '555-1')
            return a, b

    def test_merge_button_on_contacts_list(self, client, app):
        self._two_dupes(app)
        resp = client.get('/contacts')
        assert b'Merge selected' in resp.data
        assert b'/contacts/merge' in resp.data

    def test_merge_button_on_duplicates_page(self, client, app):
        self._two_dupes(app)
        resp = client.get('/contacts/duplicates')
        assert b'Merge selected' in resp.data

    def test_preview_requires_two(self, client, app):
        a, _ = self._two_dupes(app)
        token = _csrf(client)
        resp = client.post('/contacts/merge', data={
            '_csrf_token': token, 'selected': [str(a)],
        }, follow_redirects=True)
        assert b'at least two' in resp.data.lower()

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

    def test_apply_preserves_non_chosen_phone_as_custom_field(self, client, app):
        with app.app_context():
            db = get_db()
            a = models.create_contact(db, 'individual', 'Zed', None, '111')
            b = models.create_contact(db, 'individual', 'Zed', None, '222')
        token = _csrf(client)
        client.post('/contacts/merge/apply', data={
            '_csrf_token': token, 'survivor_id': str(a), 'loser_id': [str(b)],
            'field_type': 'individual', 'field_name': 'Zed',
            'field_phone': '222', 'cf_count': '0',
        }, follow_redirects=True)
        with app.app_context():
            db = get_db()
            assert models.get_contact(db, a)['phone'] == '222'   # chosen primary
            values = {c['field_value'] for c in models.get_custom_fields(db, a)}
            assert '111' in values   # the non-chosen phone is preserved, not lost

    def test_apply_rejects_what_the_contact_form_rejects(self, client, app):
        # CL-0079: merge had its own copy of the field checks and never got
        # the email/phone validation the contact form has.
        a, b = self._two_dupes(app)
        token = _csrf(client)
        resp = client.post('/contacts/merge/apply', data={
            '_csrf_token': token, 'survivor_id': str(a), 'loser_id': [str(b)],
            'field_type': 'individual', 'field_name': 'Ann',
            'field_email': 'not-an-email', 'cf_count': '0',
        }, follow_redirects=True)
        assert b'Invalid email address' in resp.data
        with app.app_context():
            assert models.get_contact(get_db(), b) is not None   # nothing merged

    def test_apply_formats_the_phone_like_the_contact_form(self, client, app):
        with app.app_context():
            db = get_db()
            import settings
            assert settings.update_settings(db, {'phone_region': 'AU'}) == []
            a = models.create_contact(db, 'individual', 'Pat', None, '0412345678')
            b = models.create_contact(db, 'individual', 'Pat', None, '0412345678')
        token = _csrf(client)
        client.post('/contacts/merge/apply', data={
            '_csrf_token': token, 'survivor_id': str(a), 'loser_id': [str(b)],
            'field_type': 'individual', 'field_name': 'Pat',
            'field_phone': '0412345678', 'cf_count': '0',
        }, follow_redirects=True)
        with app.app_context():
            db = get_db()
            assert models.get_contact(db, a)['phone'] == '+61 412 345 678'
            # The raw copy on the loser is the same number, not an extra one.
            assert models.get_custom_fields(db, a) == []

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


class TestExportStreaming:
    """CL-0067: DESIGN.md §7.2 requires both exports to stream, and the vCard
    export used to run one custom-field query per contact (an N+1)."""

    @staticmethod
    def _trace_statements(monkeypatch) -> list[str]:
        # Every connection db.get_db opens records its SQL here. PRAGMAs are
        # connection setup, not export work, so they are left out.
        import db as db_module
        real_connect = db_module.sqlite3.connect
        statements: list[str] = []

        def connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.set_trace_callback(
                lambda sql: None if sql.lstrip().upper().startswith('PRAGMA')
                else statements.append(sql)
            )
            return conn

        monkeypatch.setattr(db_module.sqlite3, 'connect', connect)
        return statements

    @staticmethod
    def _dispatch(app, url: str) -> list[bytes]:
        # The test client joins every body into one WSGI iterator, which hides
        # how the view produced it. Dispatch directly and keep the chunks the
        # view's own Response yields.
        with app.test_request_context(url):
            resp = app.full_dispatch_request()
            return [c if isinstance(c, bytes) else c.encode() for c in resp.response]

    @pytest.mark.parametrize('url, needle', [
        ('/contacts/export', b'Carol'),
        ('/contacts/export/vcard', b'FN:Carol'),
    ])
    def test_export_yields_a_chunk_per_contact(self, app, url, needle):
        # A buffered body wrapped in a one-yield generator would still report
        # is_streamed, so the chunk count is the check that can fail.
        with app.app_context():
            for name in ('Alice', 'Bob', 'Carol'):
                models.create_contact(get_db(), 'individual', name)
        chunks = self._dispatch(app, url)
        assert len(chunks) >= 3
        assert needle in b''.join(chunks)

    def test_vcard_export_query_count_does_not_grow_with_contacts(
        self, client, app, monkeypatch,
    ):
        with app.app_context():
            models.create_contact(get_db(), 'individual', 'Solo',
                                  custom_fields=[('Nickname', 'S')])
        statements = self._trace_statements(monkeypatch)
        client.get('/contacts/export/vcard').get_data()
        one = len(statements)

        with app.app_context():
            for i in range(5):
                models.create_contact(get_db(), 'individual', f'Extra {i}',
                                      custom_fields=[('Nickname', f'E{i}')])
        statements.clear()
        client.get('/contacts/export/vcard').get_data()
        assert len(statements) == one, statements

    def test_vcard_custom_fields_stay_with_their_contact(self, client, app):
        # Two contacts whose names tie under NOCASE ordering: grouping the
        # joined rows must not bleed one contact's fields into the other.
        with app.app_context():
            db = get_db()
            models.create_contact(db, 'individual', 'sam', custom_fields=[('Nickname', 'lower')])
            models.create_contact(db, 'individual', 'Sam', custom_fields=[('Nickname', 'upper')])
            models.create_contact(db, 'individual', 'Bare')
        body = client.get('/contacts/export/vcard').get_data(as_text=True)
        cards = [c for c in body.split('BEGIN:VCARD') if c.strip()]
        by_name = {
            next(line[3:] for line in c.splitlines() if line.startswith('FN:')): c
            for c in cards
        }
        assert set(by_name) == {'sam', 'Sam', 'Bare'}
        assert 'X-CL;X-LABEL=Nickname:lower' in by_name['sam']
        assert 'upper' not in by_name['sam']
        assert 'X-CL;X-LABEL=Nickname:upper' in by_name['Sam']
        assert 'X-CL' not in by_name['Bare']


class TestAccessibleNames:
    """CL-0084: controls a screen reader announced with no name, choices
    announced without their question, and state changes it never heard."""

    def test_import_file_input_is_labelled(self, client):
        html = client.get('/contacts/import').get_data(as_text=True)
        assert '<label for="import-file"' in html
        assert 'id="import-file"' in html

    def test_mapping_selects_name_their_column(self, client):
        token = _csrf(client)
        data = _upload(b'Full Name,E-mail\nAlice,a@x.com\n')
        data['_csrf_token'] = token
        html = client.post('/contacts/import', data=data,
                           content_type='multipart/form-data').get_data(as_text=True)
        assert 'aria-label="Field for column Full Name"' in html
        assert 'aria-label="Field for column E-mail"' in html
        assert re.search(r'<label>\s*Default type for rows without one:', html)

    def test_merge_page_names_its_groups_and_tags(self, client, app):
        with app.app_context():
            db = get_db()
            a = models.create_contact(db, 'individual', 'Ann', 'ann@x.com')
            b = models.create_contact(db, 'company', 'Ann', 'ann@y.com')
        token = _csrf(client)
        html = client.post('/contacts/merge', data={
            '_csrf_token': token, 'selected': [str(a), str(b)],
        }).get_data(as_text=True)
        assert '<label for="merge-tags"' in html and 'id="merge-tags"' in html
        # Each radio group is labelled by its own heading.
        for field in ('email', 'type'):
            assert f'role="radiogroup" aria-labelledby="merge-{field}"' in html
            assert f'id="merge-{field}"' in html

    def test_sorted_column_carries_aria_sort(self, client, app):
        with app.app_context():
            models.create_contact(get_db(), 'individual', 'Ann')
        html = client.get('/contacts?sort=name&dir=desc').get_data(as_text=True)
        assert re.search(r'<th aria-sort="descending"><a [^>]*sort=name', html)
        assert 'aria-sort="ascending"' not in html

    @pytest.mark.parametrize('url', ['/contacts', '/contacts/duplicates'])
    def test_selection_count_has_a_live_region(self, client, app, url):
        with app.app_context():
            db = get_db()
            models.create_contact(db, 'individual', 'Ann', 'ann@x.com')
            models.create_contact(db, 'individual', 'Ann', 'ann@x.com')
        html = client.get(url).get_data(as_text=True)
        # Outside the bulk bar, which is hidden until the first selection: a
        # live region must exist before it changes to be announced.
        assert re.search(r'<span id="bulk-status" class="visually-hidden" role="status"></span>', html)
        assert html.index('id="bulk-status"') < html.index('id="bulk-bar"')


class TestImportProfileColumns:
    """CL-0097: the saved mapping was keyed by header text, so two columns
    sharing a header kept one choice between them."""

    @staticmethod
    def _map_stage(client, csv_bytes: bytes) -> str:
        data = _upload(csv_bytes)
        data['_csrf_token'] = _csrf(client)
        return client.post('/contacts/import', data=data,
                           content_type='multipart/form-data').get_data(as_text=True)

    @staticmethod
    def _selected(html: str, col: int) -> str:
        select = re.search(rf'<select name="map_{col}".*?</select>', html, re.S)
        assert select, f'no select for column {col}'
        return re.search(r'<option value="(\w+)" selected', select.group(0)).group(1)

    def test_duplicate_header_choices_are_remembered_per_column(self, client):
        csv_bytes = b'Name,Email,Email\nAda,a@x.com,b@x.com\n'
        self._map_stage(client, csv_bytes)
        client.post('/contacts/import/apply', data={
            '_csrf_token': _csrf(client), 'csv_text': csv_bytes.decode(),
            'map_0': 'name', 'map_1': 'email', 'map_2': 'custom',
            'default_type': 'individual',
        })
        html = self._map_stage(client, csv_bytes)
        assert self._selected(html, 1) == 'email'
        assert self._selected(html, 2) == 'custom'

    def test_header_keyed_profile_saved_before_the_fix_still_prefills(self, client, app):
        import importer
        with app.app_context():
            models.save_import_profile(
                get_db(), importer.header_signature(['Name', 'Col B']),
                {'Name': 'name', 'Col B': 'notes'}, 'individual')
        html = self._map_stage(client, b'Name,Col B\nAda,hi\n')
        assert self._selected(html, 1) == 'notes'

    def test_apply_form_posts_multipart(self, client):
        # A urlencoded re-post of csv_text can grow a 1 MiB file to six times
        # its size (line breaks become %0D%0A), past MAX_CONTENT_LENGTH.
        html = self._map_stage(client, b'Name\nAda\n')
        form = re.search(r'<form[^>]*contacts/import/apply[^>]*>', html)
        assert form and 'enctype="multipart/form-data"' in form.group(0)
