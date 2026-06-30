import pytest

import settings as settings_mod
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


class TestGetSettings:
    def test_defaults_on_empty_table(self, db):
        s = settings_mod.get_settings(db)
        assert s == settings_mod.SETTINGS_DEFAULTS
        assert s is not settings_mod.SETTINGS_DEFAULTS  # a copy, not the module dict

    def test_overlays_saved_row(self, db):
        settings_mod.update_settings(db, {'theme': 'dark'})
        s = settings_mod.get_settings(db)
        assert s['theme'] == 'dark'
        assert s['timezone'] == 'UTC'  # untouched default

    def test_ignores_unknown_stored_key(self, db):
        db.execute("INSERT INTO settings (key, value) VALUES ('bogus', 'x')")
        db.commit()
        s = settings_mod.get_settings(db)
        assert 'bogus' not in s


class TestUpdateSettings:
    def test_saves_valid_values(self, db):
        errors = settings_mod.update_settings(
            db, {'theme': 'nord', 'per_page': '25', 'phone_region': 'US'}
        )
        assert errors == []
        s = settings_mod.get_settings(db)
        assert s['theme'] == 'nord'
        assert s['per_page'] == '25'
        assert s['phone_region'] == 'US'

    @pytest.mark.parametrize('key,value', [
        ('timezone', 'Mars/Phobos'),
        ('theme', 'neon'),
        ('per_page', '0'),
        ('per_page', '9999'),
        ('per_page', 'lots'),
        ('phone_region', 'ZZ'),
        ('sort', 'haircolor'),
        ('default_type', 'alien'),
    ])
    def test_rejects_invalid_value(self, db, key, value):
        errors = settings_mod.update_settings(db, {key: value})
        assert errors  # non-empty
        assert settings_mod.get_settings(db)[key] == settings_mod.SETTINGS_DEFAULTS[key]

    def test_all_or_nothing(self, db):
        # one bad key among good ones -> none persisted
        errors = settings_mod.update_settings(
            db, {'theme': 'dark', 'per_page': 'nope'}
        )
        assert errors
        s = settings_mod.get_settings(db)
        assert s['theme'] == 'comfortable' or s['theme'] == ''  # default, NOT 'dark'
        assert s['theme'] == settings_mod.SETTINGS_DEFAULTS['theme']


class TestFriendlyDate:
    def _render(self, app, db, value):
        # Exercise the filter through the app's Jinja env, inside a request so
        # g.settings is populated by the before_request hook.
        with app.test_request_context('/'):
            app.preprocess_request()  # runs before_request hooks -> g.settings
            tmpl = app.jinja_env.from_string("{{ value|friendly_date }}")
            return tmpl.render(value=value)

    def test_default_format_utc(self, app, db):
        out = self._render(app, db, '2026-06-30T14:30:00Z')
        assert out == '30 Jun 2026, 14:30'

    def test_timezone_shifts_hour(self, app, db):
        settings_mod.update_settings(db, {'timezone': 'Asia/Kolkata'})  # UTC+5:30
        out = self._render(app, db, '2026-06-30T14:30:00Z')
        assert out == '30 Jun 2026, 20:00'

    def test_custom_format_key(self, app, db):
        settings_mod.update_settings(db, {'date_format': 'iso'})
        out = self._render(app, db, '2026-06-30T14:30:00Z')
        assert out == '2026-06-30 14:30'

    def test_bad_value_falls_back_to_raw(self, app, db):
        out = self._render(app, db, 'not-a-date')
        assert out == 'not-a-date'

    def test_empty_value(self, app, db):
        out = self._render(app, db, '')
        assert out == ''


class TestPhoneUtil:
    def test_formats_za_number(self):
        import phoneutil
        assert phoneutil.format_phone('0821234567', 'ZA') == '+27 82 123 4567'

    def test_formats_us_number(self):
        import phoneutil
        assert phoneutil.format_phone('2025550123', 'US') == '+1 202-555-0123'

    def test_unparseable_returns_raw(self):
        import phoneutil
        assert phoneutil.format_phone('not a phone', 'ZA') == 'not a phone'


class TestSettingsRoute:
    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def _csrf(self, client):
        client.get('/settings')
        with client.session_transaction() as sess:
            return sess.get('_csrf_token', '')

    def test_get_renders(self, client):
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'Settings' in resp.data

    def test_post_persists_and_redirects(self, client, db):
        token = self._csrf(client)
        resp = client.post('/settings', data={
            '_csrf_token': token,
            'theme': 'dark',
            'timezone': 'UTC',
            'date_format': 'iso',
            'density': 'compact',
            'view': 'card',
            'phone_region': 'US',
            'per_page': '25',
            'sort': 'created',
            'sort_dir': 'desc',
            'default_type': 'company',
        })
        assert resp.status_code == 302
        assert settings_mod.get_settings(db)['theme'] == 'dark'

    def test_post_invalid_returns_400(self, client):
        token = self._csrf(client)
        resp = client.post('/settings', data={
            '_csrf_token': token,
            'theme': 'neon',  # invalid
        })
        assert resp.status_code == 400
        assert b'Invalid value' in resp.data

    def test_post_without_csrf_403(self, client):
        resp = client.post('/settings', data={'theme': 'dark'})
        assert resp.status_code == 403
