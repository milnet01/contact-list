import pytest

import models
from app import create_app
from db import get_db, init_db


@pytest.fixture()
def app(tmp_path):
    db_path = str(tmp_path / 'test.db')
    app = create_app({
        'TESTING': True,
        'DATABASE': db_path,
        'SECRET_KEY': 'test',
        'GOOGLE_CREDENTIALS_DIR': '/tmp/test-contact-list',
        'GOOGLE_CREDENTIALS_FILE': '/tmp/test-contact-list/creds.json',
        'GOOGLE_TOKEN_FILE': '/tmp/test-contact-list/token.json',
    })
    yield app


@pytest.fixture()
def db(app):
    with app.app_context():
        conn = get_db()
        yield conn


class TestCreateContact:
    def test_basic(self, db):
        cid = models.create_contact(db, 'individual', 'Alice', 'a@b.com', '555-1234')
        assert cid is not None

        c = models.get_contact(db, cid)
        assert c['name'] == 'Alice'
        assert c['email'] == 'a@b.com'
        assert c['type'] == 'individual'

    def test_with_custom_fields(self, db):
        cid = models.create_contact(
            db, 'company', 'Acme Inc', custom_fields=[('industry', 'Tech'), ('size', '500')]
        )
        cfs = models.get_custom_fields(db, cid)
        assert len(cfs) == 2
        names = {cf['field_name'] for cf in cfs}
        assert names == {'industry', 'size'}


class TestListContacts:
    def test_empty(self, db):
        contacts, total = models.list_contacts(db)
        assert total == 0
        assert contacts == []

    def test_pagination(self, db):
        for i in range(10):
            models.create_contact(db, 'individual', f'Person {i}')

        page1, total = models.list_contacts(db, page=1, per_page=3)
        assert total == 10
        assert len(page1) == 3

        page4, _ = models.list_contacts(db, page=4, per_page=3)
        assert len(page4) == 1

    def test_search(self, db):
        models.create_contact(db, 'individual', 'Alice Smith', 'alice@example.com')
        models.create_contact(db, 'individual', 'Bob Jones', 'bob@example.com')

        results, total = models.list_contacts(db, search='alice')
        assert total == 1
        assert results[0]['name'] == 'Alice Smith'

    def test_filter_type(self, db):
        models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'company', 'Acme')

        results, total = models.list_contacts(db, contact_type='company')
        assert total == 1
        assert results[0]['name'] == 'Acme'


class TestUpdateContact:
    def test_update_fields(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        models.update_contact(db, cid, 'company', 'Alice Corp', email='a@corp.com')

        c = models.get_contact(db, cid)
        assert c['type'] == 'company'
        assert c['name'] == 'Alice Corp'
        assert c['email'] == 'a@corp.com'

    def test_replace_custom_fields(self, db):
        cid = models.create_contact(
            db, 'individual', 'Alice', custom_fields=[('birthday', '1990-01-01')]
        )
        models.update_contact(
            db, cid, 'individual', 'Alice', custom_fields=[('hobby', 'Reading')]
        )
        cfs = models.get_custom_fields(db, cid)
        assert len(cfs) == 1
        assert cfs[0]['field_name'] == 'hobby'


class TestDeleteContact:
    def test_delete(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        models.delete_contact(db, cid)
        assert models.get_contact(db, cid) is None

    def test_cascade_custom_fields(self, db):
        cid = models.create_contact(
            db, 'individual', 'Alice', custom_fields=[('x', 'y')]
        )
        models.delete_contact(db, cid)
        cfs = models.get_custom_fields(db, cid)
        assert len(cfs) == 0


class TestValidFieldName:
    def test_valid(self):
        assert models.valid_field_name('birthday')
        assert models.valid_field_name('Bank Account')
        assert models.valid_field_name('field_1')

    def test_invalid(self):
        assert not models.valid_field_name('')
        assert not models.valid_field_name('a' * 65)
        assert not models.valid_field_name('field<script>')
        assert not models.valid_field_name('field;DROP')


class TestOrdering:
    def test_default_name_order(self, db):
        models.create_contact(db, 'individual', 'Zebra')
        models.create_contact(db, 'individual', 'Apple')
        models.create_contact(db, 'individual', 'Mango')
        contacts, _ = models.list_contacts(db)
        assert contacts[0]['name'] == 'Apple'
        assert contacts[1]['name'] == 'Mango'
        assert contacts[2]['name'] == 'Zebra'

    def test_sort_by_type(self, db):
        models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'company', 'Acme')
        contacts, _ = models.list_contacts(db, sort='type', sort_dir='asc')
        assert contacts[0]['type'] == 'company'
        assert contacts[1]['type'] == 'individual'

    def test_sort_descending(self, db):
        models.create_contact(db, 'individual', 'Apple')
        models.create_contact(db, 'individual', 'Zebra')
        contacts, _ = models.list_contacts(db, sort='name', sort_dir='desc')
        assert contacts[0]['name'] == 'Zebra'
        assert contacts[1]['name'] == 'Apple'


class TestFindDuplicates:
    def test_no_duplicates(self, db):
        models.create_contact(db, 'individual', 'Alice')
        warnings = models.find_duplicates(db, 'Bob')
        assert warnings == []

    def test_name_duplicate(self, db):
        models.create_contact(db, 'individual', 'Alice')
        warnings = models.find_duplicates(db, 'Alice')
        assert len(warnings) == 1
        assert 'Alice' in warnings[0]

    def test_phone_duplicate(self, db):
        models.create_contact(db, 'individual', 'Alice', phone='+27 11 555 0001')
        warnings = models.find_duplicates(db, 'Bob', phone='+27 11 555 0001')
        assert len(warnings) == 1
        assert 'Phone' in warnings[0]

    def test_exclude_self(self, db):
        cid = models.create_contact(db, 'individual', 'Alice', phone='+27 11 555 0001')
        warnings = models.find_duplicates(db, 'Alice', phone='+27 11 555 0001', exclude_id=cid)
        assert warnings == []


class TestFindAllDuplicates:
    def test_no_duplicates(self, db):
        models.create_contact(db, 'individual', 'Alice', 'a@b.com', '555-0001')
        models.create_contact(db, 'individual', 'Bob', 'b@b.com', '555-0002')
        dupes = models.find_all_duplicates(db)
        assert dupes['name'] == []
        assert dupes['email'] == []
        assert dupes['phone'] == []

    def test_duplicate_names(self, db):
        models.create_contact(db, 'individual', 'Alice', 'a1@b.com')
        models.create_contact(db, 'individual', 'Alice', 'a2@b.com')
        dupes = models.find_all_duplicates(db)
        assert len(dupes['name']) == 1
        assert len(dupes['name'][0]) == 2

    def test_duplicate_emails(self, db):
        models.create_contact(db, 'individual', 'Alice', 'shared@b.com')
        models.create_contact(db, 'individual', 'Bob', 'shared@b.com')
        dupes = models.find_all_duplicates(db)
        assert len(dupes['email']) == 1
        assert len(dupes['email'][0]) == 2

    def test_duplicate_phones(self, db):
        models.create_contact(db, 'individual', 'Alice', phone='555-0001')
        models.create_contact(db, 'individual', 'Bob', phone='555-0001')
        dupes = models.find_all_duplicates(db)
        assert len(dupes['phone']) == 1
        assert len(dupes['phone'][0]) == 2

    def test_ignores_null_email_phone(self, db):
        models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'individual', 'Bob')
        dupes = models.find_all_duplicates(db)
        assert dupes['email'] == []
        assert dupes['phone'] == []


class TestExportContacts:
    def test_export(self, db):
        models.create_contact(db, 'individual', 'Alice', 'a@b.com', notes='Test note')
        models.create_contact(db, 'company', 'Acme')
        rows = models.export_contacts(db)
        assert len(rows) == 2
        assert rows[0]['name'] == 'Acme'  # alphabetical
        assert rows[0]['notes'] is None
        assert rows[1]['notes'] == 'Test note'


class TestCountContacts:
    def test_count(self, db):
        models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'company', 'Acme')
        assert models.count_contacts(db) == 2
        assert models.count_contacts(db, contact_type='company') == 1


class TestEscapeLike:
    def test_special_chars(self, db):
        models.create_contact(db, 'individual', '100% Organic')
        results, total = models.list_contacts(db, search='100%')
        assert total == 1
