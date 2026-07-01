"""Tests for CSV/vCard import, merge, and their data-layer helpers
(CL-0022, CL-0023, CL-0024)."""

from __future__ import annotations

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


class TestSanitizeFieldName:
    def test_valid_passthrough(self):
        assert models.sanitize_field_name('Work Email') == 'Work Email'

    def test_strips_illegal_chars(self):
        # Parentheses are rejected by valid_field_name; sanitising must remove
        # them so a derived label like a vCard TYPE never trips validation.
        assert models.sanitize_field_name('Email (work)') == 'Email work'

    def test_collapses_and_trims(self):
        assert models.sanitize_field_name('  a---b  ') == 'a b'

    def test_all_illegal_returns_empty(self):
        assert models.sanitize_field_name('!!!') == ''

    def test_truncates_to_64(self):
        assert models.sanitize_field_name('a' * 100) == 'a' * 64

    def test_result_passes_valid_field_name(self):
        for raw in ['Email (work)', 'a/b\\c', 'Ünïcodé', 'phone#1']:
            out = models.sanitize_field_name(raw)
            assert out == '' or models.valid_field_name(out)


class TestImportContact:
    def test_creates_new(self, db):
        cid, action = models.import_contact(
            db, {'type': 'individual', 'name': 'Alice', 'email': 'a@b.com'}, []
        )
        assert action == 'created'
        assert models.get_contact(db, cid)['name'] == 'Alice'

    def test_matches_existing_by_email_case_insensitive(self, db):
        existing = models.create_contact(db, 'individual', 'Alice', 'a@b.com')
        cid, action = models.import_contact(
            db, {'type': 'individual', 'name': 'Alice Smith', 'email': 'A@B.COM'}, []
        )
        assert action == 'updated'
        assert cid == existing

    def test_matches_existing_by_name_when_no_email(self, db):
        existing = models.create_contact(db, 'individual', 'Bob')
        cid, action = models.import_contact(db, {'type': 'individual', 'name': 'bob'}, [])
        assert action == 'updated'
        assert cid == existing

    def test_additive_fills_blank_only_never_overwrites(self, db):
        cid = models.create_contact(db, 'individual', 'Carol', 'c@x.com', None)
        models.import_contact(
            db,
            {'type': 'individual', 'name': 'Carol', 'email': 'other@x.com',
             'phone': '555-9', 'notes': 'hi'},
            [],
        )
        c = models.get_contact(db, cid)
        assert c['email'] == 'c@x.com'   # existing non-empty kept
        assert c['phone'] == '555-9'     # was blank -> filled
        assert c['notes'] == 'hi'        # was blank -> filled

    def test_additive_custom_fields_no_duplicate_name(self, db):
        cid = models.create_contact(
            db, 'individual', 'Dave', custom_fields=[('Nickname', 'D')]
        )
        models.import_contact(
            db, {'type': 'individual', 'name': 'Dave'},
            [('nickname', 'Davey'), ('City', 'Cape Town')],
        )
        cfs = {cf['field_name'].lower(): cf['field_value'] for cf in
               models.get_custom_fields(db, cid)}
        assert cfs['nickname'] == 'D'    # existing kept, case-insensitive
        assert cfs['city'] == 'Cape Town'  # new added

    def test_blank_email_falls_through_to_name(self, db):
        # An existing contact with an empty-string email must not match an
        # imported row whose email is also blank.
        existing = models.create_contact(db, 'individual', 'Erin')
        db.execute("UPDATE contacts SET email = '' WHERE id = ?", [existing])
        db.commit()
        cid, action = models.import_contact(
            db, {'type': 'individual', 'name': 'Erin', 'email': ''}, []
        )
        assert action == 'updated'
        assert cid == existing


class TestMergeContacts:
    def test_merges_and_deletes_losers(self, db):
        a = models.create_contact(db, 'individual', 'Ann', 'ann@x.com')
        b = models.create_contact(db, 'individual', 'Ann', None, '555-1')
        models.merge_contacts(
            db, a, [b],
            {'type': 'individual', 'name': 'Ann', 'email': 'ann@x.com',
             'phone': '555-1', 'notes': None},
            [],
        )
        survivor = models.get_contact(db, a)
        assert survivor['email'] == 'ann@x.com'
        assert survivor['phone'] == '555-1'
        assert models.get_contact(db, b) is None

    def test_cascade_deletes_loser_custom_fields(self, db):
        a = models.create_contact(db, 'individual', 'Ann')
        b = models.create_contact(db, 'individual', 'Ann',
                                  custom_fields=[('X', '1')])
        b_cf_before = models.get_custom_fields(db, b)
        assert len(b_cf_before) == 1
        models.merge_contacts(db, a, [b],
                              {'type': 'individual', 'name': 'Ann',
                               'email': None, 'phone': None, 'notes': None}, [])
        # Loser gone; its custom_fields row cascaded away (no orphan).
        orphan = db.execute(
            'SELECT COUNT(*) FROM custom_fields WHERE contact_id = ?', [b]
        ).fetchone()[0]
        assert orphan == 0

    def test_rejects_survivor_in_losers(self, db):
        a = models.create_contact(db, 'individual', 'Ann')
        with pytest.raises(ValueError):
            models.merge_contacts(db, a, [a],
                                  {'type': 'individual', 'name': 'Ann',
                                   'email': None, 'phone': None, 'notes': None}, [])

    def test_rejects_empty_losers(self, db):
        a = models.create_contact(db, 'individual', 'Ann')
        with pytest.raises(ValueError):
            models.merge_contacts(db, a, [],
                                  {'type': 'individual', 'name': 'Ann',
                                   'email': None, 'phone': None, 'notes': None}, [])


class TestImportProfiles:
    def test_missing_returns_none(self, db):
        assert models.get_import_profile(db, 'nope') is None

    def test_save_then_get_roundtrip(self, db):
        models.save_import_profile(db, 'sig1', {'Name': 'name'}, 'company')
        prof = models.get_import_profile(db, 'sig1')
        assert prof['mapping'] == {'Name': 'name'}
        assert prof['default_type'] == 'company'

    def test_save_upserts(self, db):
        models.save_import_profile(db, 'sig1', {'Name': 'name'}, 'individual')
        models.save_import_profile(db, 'sig1', {'Full': 'name'}, 'company')
        prof = models.get_import_profile(db, 'sig1')
        assert prof['mapping'] == {'Full': 'name'}
        assert prof['default_type'] == 'company'
