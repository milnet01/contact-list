import datetime
import io

import pytest

from app import create_app


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


def _get_csrf(client) -> str:
    """Fetch a page to populate the CSRF token in the session."""
    client.get('/contacts/new')
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


class TestIndex:
    def test_redirect(self, client):
        resp = client.get('/')
        assert resp.status_code == 302
        assert '/contacts' in resp.headers['Location']


class TestContactList:
    def test_empty(self, client):
        resp = client.get('/contacts')
        assert resp.status_code == 200
        assert b'No contacts yet' in resp.data


class TestCreateContact:
    def test_success(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Alice Test',
            'email': 'alice@test.com',
            'phone': '555-0001',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Alice Test' in resp.data

    def test_missing_name(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': '',
        })
        assert resp.status_code == 400
        assert b'Name is required' in resp.data

    def test_csrf_required(self, client):
        resp = client.post('/contacts', data={
            'type': 'individual',
            'name': 'Hacker',
        })
        assert resp.status_code == 403

    def test_with_custom_fields(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Bob',
            'cf_name': ['birthday', 'workplace'],
            'cf_value': ['1990-05-15', 'Acme Corp'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'birthday' in resp.data
        assert b'1990-05-15' in resp.data

    def test_invalid_custom_field_name(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Eve',
            'cf_name': ['<script>'],
            'cf_value': ['bad'],
        })
        assert resp.status_code == 400


class TestContactDetail:
    def test_view(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'company',
            'name': 'Widgets Inc',
            'email': 'info@widgets.com',
        })
        resp = client.get('/contacts/1')
        assert resp.status_code == 200
        assert b'Widgets Inc' in resp.data

    def test_not_found(self, client):
        resp = client.get('/contacts/9999')
        assert resp.status_code == 404


class TestUpdateContact:
    def test_update(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Charlie',
        })
        resp = client.post('/contacts/1', data={
            '_csrf_token': token,
            'type': 'company',
            'name': 'Charlie Corp',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Charlie Corp' in resp.data
        assert b'company' in resp.data


class TestDeleteContact:
    def test_delete(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Doomed',
        })
        resp = client.post('/contacts/1/delete', data={
            '_csrf_token': token,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Doomed' not in resp.data


class TestSearch:
    def test_search_by_name(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice Wonderland',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Bob Builder',
        })
        resp = client.get('/contacts?q=alice')
        assert resp.status_code == 200
        assert b'Alice Wonderland' in resp.data
        assert b'Bob Builder' not in resp.data

    def test_filter_type(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'company', 'name': 'Acme',
        })
        resp = client.get('/contacts?type=company')
        assert b'Acme' in resp.data
        assert b'Alice' not in resp.data


class TestSyncPage:
    def test_shows_setup(self, client):
        resp = client.get('/sync')
        assert resp.status_code == 200
        assert b'Setup Required' in resp.data


class TestXSSPrevention:
    def test_name_escaped(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': '<img src=x onerror="alert(1)">',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'<img src=x' not in resp.data
        assert b'&lt;img' in resp.data


class TestCSVExport:
    def test_export_empty(self, client):
        resp = client.get('/contacts/export')
        assert resp.status_code == 200
        assert resp.content_type == 'text/csv; charset=utf-8'
        assert b'Name,Type,Email,Phone' in resp.data

    def test_export_with_data(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Alice Test',
            'email': 'alice@test.com',
        })
        resp = client.get('/contacts/export')
        assert b'Alice Test' in resp.data
        assert b'alice@test.com' in resp.data


class TestSorting:
    def test_sort_by_type(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'company', 'name': 'Acme',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        resp = client.get('/contacts?sort=type&dir=asc')
        assert resp.status_code == 200
        data = resp.data
        acme_pos = data.find(b'Acme')
        alice_pos = data.find(b'Alice')
        assert acme_pos < alice_pos

    def test_sort_descending(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Apple',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Zebra',
        })
        resp = client.get('/contacts?sort=name&dir=desc')
        data = resp.data
        zebra_pos = data.find(b'Zebra')
        apple_pos = data.find(b'Apple')
        assert zebra_pos < apple_pos


class TestPaginationBoundary:
    def test_page_beyond_total(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        resp = client.get('/contacts?page=9999')
        assert resp.status_code == 200
        assert b'Alice' in resp.data


class TestDuplicateDetection:
    def test_duplicate_name_warning(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        resp = client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already exists' in resp.data


class TestDuplicatesPage:
    def test_no_duplicates(self, client):
        resp = client.get('/contacts/duplicates')
        assert resp.status_code == 200
        assert b'No duplicates found' in resp.data

    def test_duplicate_names(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
            'email': 'alice1@test.com',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
            'email': 'alice2@test.com',
        })
        resp = client.get('/contacts/duplicates')
        assert resp.status_code == 200
        assert b'Duplicate Names' in resp.data
        assert resp.data.count(b'Alice') >= 2

    def test_duplicate_emails(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
            'email': 'shared@test.com',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Bob',
            'email': 'shared@test.com',
        })
        resp = client.get('/contacts/duplicates')
        assert resp.status_code == 200
        assert b'Duplicate Emails' in resp.data

    def test_duplicate_phones(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
            'phone': '555-0001',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Bob',
            'phone': '555-0001',
        })
        resp = client.get('/contacts/duplicates')
        assert resp.status_code == 200
        assert b'Duplicate Phone' in resp.data


class TestBulkDelete:
    def test_bulk_delete(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Bob',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Charlie',
        })
        resp = client.post('/contacts/bulk-delete', data={
            '_csrf_token': token,
            'selected': ['1', '2'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Deleted 2 contact' in resp.data
        assert b'Alice' not in resp.data
        assert b'Charlie' in resp.data

    def test_bulk_delete_empty(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts/bulk-delete', data={
            '_csrf_token': token,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'No contacts selected' in resp.data


class TestCustomFieldLimits:
    def test_duplicate_field_name(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Bob',
            'cf_name': ['birthday', 'birthday'],
            'cf_value': ['1990-01-01', '2000-01-01'],
        })
        assert resp.status_code == 400
        assert b'Duplicate field name' in resp.data


class TestLetterFilter:
    def test_hash_filter(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': '123 Corp',
        })
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        resp = client.get('/contacts?letter=%23')
        assert b'123 Corp' in resp.data
        assert b'Alice' not in resp.data

    def test_letter_case_insensitive(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'alice',
        })
        resp = client.get('/contacts?letter=A')
        assert b'alice' in resp.data


class TestFriendlyDate:
    def test_timestamp_formatted(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Alice',
        })
        resp = client.get('/contacts/1')
        assert resp.status_code == 200
        # Should have human-readable date, not raw ISO format with T
        assert b'Created:' in resp.data


class TestSecurityHeaders:
    def test_csp_header(self, client):
        resp = client.get('/contacts')
        csp = resp.headers.get('Content-Security-Policy', '')
        assert "default-src 'self'" in csp
        assert "form-action 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

    def test_other_headers(self, client):
        resp = client.get('/contacts')
        assert resp.headers['X-Content-Type-Options'] == 'nosniff'
        assert resp.headers['X-Frame-Options'] == 'DENY'
        assert 'Permissions-Policy' in resp.headers


class TestOpenRedirect:
    def test_safe_ref_rejects_protocol_relative(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Test User',
        })
        resp = client.post('/contacts/1/delete', data={
            '_csrf_token': token,
            'ref': '//evil.com',
        })
        assert resp.status_code == 302
        assert '//evil.com' not in resp.headers['Location']

    def test_safe_ref_allows_local_paths(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token,
            'type': 'individual',
            'name': 'Test User',
        })
        resp = client.post('/contacts/1/delete', data={
            '_csrf_token': token,
            'ref': '/contacts?page=3&letter=B',
        })
        assert resp.status_code == 302
        assert '/contacts?page=3&letter=B' in resp.headers['Location']


# --- Contact photos (CL-0026) ----------------------------------------------

_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 40


def _create_contact(client, token, name='Photo Person', photo=None):
    """POST create; return the new contact id parsed from the redirect."""
    data = {'_csrf_token': token, 'type': 'individual', 'name': name}
    if photo is not None:
        data['photo'] = (io.BytesIO(photo), 'a.png')
    resp = client.post('/contacts', data=data, content_type='multipart/form-data')
    assert resp.status_code == 302
    loc = resp.headers['Location']
    return int(loc.split('/contacts/')[1].split('?')[0])


class TestContactPhotos:
    def test_serve_404_without_photo(self, client):
        token = _get_csrf(client)
        cid = _create_contact(client, token)
        assert client.get(f'/contacts/{cid}/photo').status_code == 404

    def test_upload_and_serve(self, client):
        token = _get_csrf(client)
        cid = _create_contact(client, token, photo=_PNG)
        resp = client.get(f'/contacts/{cid}/photo')
        assert resp.status_code == 200
        assert resp.mimetype == 'image/png'
        assert resp.data == _PNG

    def test_photo_response_is_cacheable(self, client):
        # CL-0034: browsers should cache avatars instead of revalidating each
        # navigation. The route sets a max-age; ETag/Last-Modified still allow
        # conditional revalidation once it expires.
        token = _get_csrf(client)
        cid = _create_contact(client, token, photo=_PNG)
        resp = client.get(f'/contacts/{cid}/photo')
        assert resp.cache_control.max_age == 86400

    def test_detail_shows_img_when_photo(self, client):
        token = _get_csrf(client)
        cid = _create_contact(client, token, photo=_PNG)
        resp = client.get(f'/contacts/{cid}')
        assert f'/contacts/{cid}/photo'.encode() in resp.data

    def test_list_shows_img_when_photo(self, client):
        token = _get_csrf(client)
        cid = _create_contact(client, token, photo=_PNG)
        resp = client.get('/contacts')
        assert f'/contacts/{cid}/photo'.encode() in resp.data

    def test_upload_non_image_rejected_but_contact_saved(self, client):
        token = _get_csrf(client)
        data = {
            '_csrf_token': token, 'type': 'individual', 'name': 'No Photo',
            'photo': (io.BytesIO(b'this is not an image'), 'x.png'),
        }
        resp = client.post('/contacts', data=data,
                           content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        assert b'No Photo' in resp.data           # contact still saved
        assert b'Photo must be' in resp.data      # friendly flash shown

    def test_remove_photo(self, client):
        token = _get_csrf(client)
        cid = _create_contact(client, token, photo=_PNG)
        assert client.get(f'/contacts/{cid}/photo').status_code == 200
        client.post(f'/contacts/{cid}', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Photo Person',
            'remove_photo': '1',
        }, content_type='multipart/form-data')
        assert client.get(f'/contacts/{cid}/photo').status_code == 404

    def test_delete_unlinks_file(self, client):
        import os
        token = _get_csrf(client)
        cid = _create_contact(client, token, photo=_PNG)
        photos_dir = client.application.config['PHOTOS_DIR']
        assert os.path.exists(os.path.join(photos_dir, f'{cid}.png'))
        client.post(f'/contacts/{cid}/delete', data={'_csrf_token': token})
        assert not os.path.exists(os.path.join(photos_dir, f'{cid}.png'))

    def test_merge_unlinks_loser_file(self, client):
        import os
        token = _get_csrf(client)
        survivor = _create_contact(client, token, name='Survivor')
        loser = _create_contact(client, token, name='Loser', photo=_PNG)
        photos_dir = client.application.config['PHOTOS_DIR']
        assert os.path.exists(os.path.join(photos_dir, f'{loser}.png'))
        client.post('/contacts/merge/apply', data={
            '_csrf_token': token,
            'survivor_id': str(survivor),
            'loser_id': str(loser),
            'field_type': 'individual',
            'field_name': 'Survivor',
        })
        assert not os.path.exists(os.path.join(photos_dir, f'{loser}.png'))


# --- Upcoming birthdays (CL-0038) ------------------------------------------

class TestUpcomingBirthdaysView:
    def _create_with_birthday(self, client, token, name, bday):
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': name,
            'cf_name': ['birthday'], 'cf_value': [bday],
        }, follow_redirects=True)

    def test_nav_has_birthdays_link(self, client):
        resp = client.get('/contacts')
        assert b'/contacts/birthdays' in resp.data

    def test_todays_birthday_is_shown(self, client):
        token = _get_csrf(client)
        mmdd = datetime.date.today().strftime('%m-%d')
        self._create_with_birthday(client, token, 'Birthday Person', mmdd)
        resp = client.get('/contacts/birthdays')
        assert resp.status_code == 200
        assert b'Birthday Person' in resp.data

    def test_far_birthday_excluded_by_default(self, client):
        token = _get_csrf(client)
        far = (datetime.date.today() + datetime.timedelta(days=100)).strftime('%m-%d')
        self._create_with_birthday(client, token, 'Far Away', far)
        resp = client.get('/contacts/birthdays')
        assert b'Far Away' not in resp.data

    def test_days_param_widens_window(self, client):
        token = _get_csrf(client)
        d = (datetime.date.today() + datetime.timedelta(days=100)).strftime('%m-%d')
        self._create_with_birthday(client, token, 'Hundred Days', d)
        resp = client.get('/contacts/birthdays?days=200')
        assert b'Hundred Days' in resp.data

    def test_empty_state(self, client):
        resp = client.get('/contacts/birthdays')
        assert resp.status_code == 200
        assert b'No upcoming birthdays' in resp.data


# --- Honest last-edited + last-synced display (CL-0033) ---------------------

class TestEditedDisplay:
    def test_footer_shows_last_synced(self, client):
        resp = client.get('/contacts')
        assert b'Last synced' in resp.data  # "Never" when sync_state empty

    def test_detail_hides_last_edited_for_pulled_contact(self, client):
        # A pull-imported contact has no contact_edits row -> no "Last edited".
        import google_sync
        with client.application.app_context():
            from db import get_db
            db = get_db()
            google_sync._upsert_person(
                db, {'resourceName': 'people/x1',
                     'names': [{'displayName': 'Synced Sam'}]},
                'US', client.application.config)
            db.commit()
            cid = db.execute(
                "SELECT id FROM contacts WHERE name='Synced Sam'").fetchone()['id']
        resp = client.get(f'/contacts/{cid}')
        assert resp.status_code == 200
        assert b'Created:' in resp.data
        assert b'Last edited' not in resp.data

    def test_detail_shows_last_edited_after_user_edit(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Editable Ed'})
        with client.application.app_context():
            from db import get_db
            db = get_db()
            cid = db.execute(
                "SELECT id FROM contacts WHERE name='Editable Ed'").fetchone()['id']
            # Force edited_at clearly after created_at so the != guard fires.
            db.execute(
                "UPDATE contact_edits SET edited_at='2099-01-01T00:00:00Z' "
                "WHERE contact_id=?", [cid])
            db.commit()
        resp = client.get(f'/contacts/{cid}')
        assert b'Last edited' in resp.data

    def test_list_shows_edited_hint(self, client):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Listed Liz'})
        resp = client.get('/contacts')
        assert b'edited-hint' in resp.data


class TestFavourites:
    """CL-0039 favourite / pinned contacts — route + display."""

    def _make(self, app, name='Alice', ctype='individual'):
        import models
        from db import get_db
        with app.app_context():
            return models.create_contact(get_db(), ctype, name)

    def _is_fav(self, app, cid):
        import models
        from db import get_db
        with app.app_context():
            return models.is_favourite(get_db(), cid)

    def test_star_sets_favourite(self, client, app):
        cid = self._make(app)
        token = _get_csrf(client)
        resp = client.post(f'/contacts/{cid}/favourite',
                           data={'_csrf_token': token, 'favourite': '1'})
        assert resp.status_code == 302
        assert self._is_fav(app, cid) is True

    def test_unstar_removes_favourite(self, client, app):
        cid = self._make(app)
        token = _get_csrf(client)
        client.post(f'/contacts/{cid}/favourite',
                    data={'_csrf_token': token, 'favourite': '1'})
        client.post(f'/contacts/{cid}/favourite',
                    data={'_csrf_token': token, 'favourite': '0'})
        assert self._is_fav(app, cid) is False

    def test_missing_csrf_rejected(self, client, app):
        cid = self._make(app)
        resp = client.post(f'/contacts/{cid}/favourite', data={'favourite': '1'})
        assert resp.status_code == 403
        assert self._is_fav(app, cid) is False

    def test_unknown_id_404(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts/99999/favourite',
                           data={'_csrf_token': token, 'favourite': '1'})
        assert resp.status_code == 404

    def test_missing_field_unstars(self, client, app):
        # 'favourite' absent resolves to un-star (desired-state, by design).
        cid = self._make(app)
        token = _get_csrf(client)
        client.post(f'/contacts/{cid}/favourite',
                    data={'_csrf_token': token, 'favourite': '1'})
        resp = client.post(f'/contacts/{cid}/favourite', data={'_csrf_token': token})
        assert resp.status_code == 302
        assert self._is_fav(app, cid) is False

    def test_safe_ref_honoured(self, client, app):
        cid = self._make(app)
        token = _get_csrf(client)
        resp = client.post(f'/contacts/{cid}/favourite',
                           data={'_csrf_token': token, 'favourite': '1',
                                 'ref': '/contacts?letter=A'})
        assert resp.status_code == 302
        assert 'letter=A' in resp.headers['Location']

    def test_unsafe_ref_falls_back_to_detail(self, client, app):
        cid = self._make(app)
        token = _get_csrf(client)
        resp = client.post(f'/contacts/{cid}/favourite',
                           data={'_csrf_token': token, 'favourite': '1',
                                 'ref': '//evil.com'})
        assert resp.status_code == 302
        assert f'/contacts/{cid}' in resp.headers['Location']
        assert 'evil.com' not in resp.headers['Location']

    def test_no_ref_redirects_to_detail(self, client, app):
        cid = self._make(app)
        token = _get_csrf(client)
        resp = client.post(f'/contacts/{cid}/favourite',
                           data={'_csrf_token': token, 'favourite': '1'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/contacts/{cid}')

    def test_list_shows_star_and_toggle_form(self, client, app):
        cid = self._make(app, name='Zoe')
        token = _get_csrf(client)
        client.post(f'/contacts/{cid}/favourite',
                    data={'_csrf_token': token, 'favourite': '1'})
        resp = client.get('/contacts')
        assert resp.status_code == 200
        assert '★'.encode() in resp.data
        assert f'id="fav-{cid}"'.encode() in resp.data

    def test_detail_shows_star_toggle(self, client, app):
        cid = self._make(app, name='Zoe')
        resp = client.get(f'/contacts/{cid}')
        assert resp.status_code == 200
        assert f'/contacts/{cid}/favourite'.encode() in resp.data
        assert '☆'.encode() in resp.data

    def test_favourite_pins_to_top_of_list(self, client, app):
        self._make(app, name='Aaron')
        zoe = self._make(app, name='Zoe')
        token = _get_csrf(client)
        client.post(f'/contacts/{zoe}/favourite',
                    data={'_csrf_token': token, 'favourite': '1'})
        body = client.get('/contacts').data.decode()
        assert body.index('Zoe') < body.index('Aaron')
