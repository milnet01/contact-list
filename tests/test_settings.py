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
