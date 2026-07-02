import datetime

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

    def test_search_matches_notes(self, db):
        # Search should look inside a contact's notes, not just name/email/phone
        # (CL-0025). "plumber" appears only in the notes here.
        models.create_contact(db, 'individual', 'Alice Smith', notes='Great plumber')
        models.create_contact(db, 'individual', 'Bob Jones')

        results, total = models.list_contacts(db, search='plumber')
        assert total == 1
        assert results[0]['name'] == 'Alice Smith'

    def test_search_matches_custom_field_value(self, db):
        # Search should look inside custom field values (CL-0025). "Acme" appears
        # only in a custom field's value here.
        models.create_contact(
            db, 'individual', 'Alice Smith', custom_fields=[('employer', 'Acme Corp')]
        )
        models.create_contact(db, 'individual', 'Bob Jones')

        results, total = models.list_contacts(db, search='acme')
        assert total == 1
        assert results[0]['name'] == 'Alice Smith'

    def test_search_no_duplicate_rows_across_custom_fields(self, db):
        # A contact whose search term appears in several custom fields must still
        # be returned exactly once (CL-0025 — no row fan-out from the join).
        cid = models.create_contact(
            db, 'individual', 'Zoe Zed',
            custom_fields=[('nick', 'Zed'), ('team', 'Zed Squad')],
        )
        results, total = models.list_contacts(db, search='zed')
        assert total == 1
        assert results[0]['id'] == cid

    def test_filter_type(self, db):
        models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'company', 'Acme')

        results, total = models.list_contacts(db, contact_type='company')
        assert total == 1
        assert results[0]['name'] == 'Acme'

    def test_over_range_page_clamped_to_last(self, db):
        # An over-range page returns the last populated page's rows (not empty),
        # so the route can reuse this total instead of a second COUNT (CL-0017).
        for i in range(10):
            models.create_contact(db, 'individual', f'Person {i}')

        page99, total = models.list_contacts(db, page=99, per_page=3)
        assert total == 10
        assert len(page99) == 1  # last page (4 of 4) holds the 10th contact


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

    def test_duplicate_phones_normalized(self, db):
        # Same ZA number typed two different ways must land in one group, the
        # same way the on-create warning normalizes (find_duplicates) — CL-0027.
        models.create_contact(db, 'individual', 'Alice', phone='+27 11 555 0001')
        models.create_contact(db, 'individual', 'Bob', phone='0115550001')
        dupes = models.find_all_duplicates(db, region='ZA')
        assert len(dupes['phone']) == 1
        assert len(dupes['phone'][0]) == 2


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
        # list_contacts returns (rows, total); the total honours the same
        # filters the old count_contacts() helper reported (removed as dead
        # code once every caller moved to list_contacts's total — CL-0017).
        assert models.list_contacts(db)[1] == 2
        assert models.list_contacts(db, contact_type='company')[1] == 1


class TestContactTypeGuard:
    def test_create_rejects_bad_type(self, db):
        import pytest
        with pytest.raises(ValueError, match='Invalid contact type'):
            models.create_contact(db, 'alien', 'Bad')

    def test_update_rejects_bad_type(self, db):
        import pytest
        cid = models.create_contact(db, 'individual', 'Alice')
        with pytest.raises(ValueError, match='Invalid contact type'):
            models.update_contact(db, cid, 'alien', 'Alice')

    def test_valid_types_accepted(self, db):
        assert models.create_contact(db, 'individual', 'Alice') is not None
        assert models.create_contact(db, 'company', 'Acme') is not None


class TestPhoneNormalizedDuplicates:
    def test_same_number_different_format_flagged(self, db):
        models.create_contact(db, 'individual', 'Alice', phone='+1 202-555-0123')
        # A differently-typed form of the same US number.
        warnings = models.find_duplicates(db, 'Bob', '2025550123', region='US')
        assert any('already used by "Alice"' in w for w in warnings)

    def test_different_number_not_flagged(self, db):
        models.create_contact(db, 'individual', 'Alice', phone='+1 202-555-0123')
        warnings = models.find_duplicates(db, 'Bob', '+1 202-555-9999', region='US')
        assert not any('already used' in w for w in warnings)

    def test_unparseable_phone_falls_back_to_exact(self, db):
        models.create_contact(db, 'individual', 'Alice', phone='ext-12345')
        warnings = models.find_duplicates(db, 'Bob', 'ext-12345', region='US')
        assert any('already used by "Alice"' in w for w in warnings)


class TestAccentFoldedNav:
    def test_accented_initial_buckets_under_base_letter(self, db):
        models.create_contact(db, 'individual', 'Élodie')
        models.create_contact(db, 'individual', 'Eric')
        counts = models.get_letter_counts(db)
        assert counts.get('E') == 2  # both fold to 'E'
        assert '#' not in counts

    def test_letter_filter_matches_accented(self, db):
        models.create_contact(db, 'individual', 'Élodie')
        results, total = models.list_contacts(db, letter='E')
        assert total == 1
        assert results[0]['name'] == 'Élodie'

    def test_non_latin_buckets_under_hash(self, db):
        models.create_contact(db, 'individual', '你好')
        counts = models.get_letter_counts(db)
        assert counts.get('#') == 1
        results, total = models.list_contacts(db, letter='#')
        assert total == 1


class TestTypeCounts:
    def test_breakdown(self, db):
        models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'individual', 'Bob')
        models.create_contact(db, 'company', 'Acme')
        assert models.get_type_counts(db) == {'individual': 2, 'company': 1}

    def test_empty(self, db):
        assert models.get_type_counts(db) == {}


class TestEscapeLike:
    def test_special_chars(self, db):
        models.create_contact(db, 'individual', '100% Organic')
        models.create_contact(db, 'individual', '1000 Oaks')
        results, total = models.list_contacts(db, search='100%')
        assert total == 1
        assert results[0]['name'] == '100% Organic'


class TestCustomFieldValidation:
    def test_create_rejects_bad_field_name(self, db):
        with pytest.raises(ValueError):
            models.create_contact(
                db, 'individual', 'X', custom_fields=[('bad;name', 'v')]
            )

    def test_update_rejects_bad_field_name_without_deleting(self, db):
        cid = models.create_contact(
            db, 'individual', 'X', custom_fields=[('Phone2', '555')]
        )
        with pytest.raises(ValueError):
            models.update_contact(
                db, cid, 'individual', 'X', custom_fields=[('bad;name', 'v')]
            )
        # The rejected update must run before any mutation, so the existing
        # custom field survives.
        cfs = models.get_custom_fields(db, cid)
        assert any(cf['field_name'] == 'Phone2' for cf in cfs)


class TestUpdateAtomicity:
    def test_failed_update_does_not_wipe_existing_custom_fields(self, db):
        cid = models.create_contact(
            db, 'individual', 'Alice', custom_fields=[('Phone2', '555')]
        )
        # A NULL field value violates the NOT NULL constraint, failing the
        # re-insert *after* the UPDATE + DELETE. Without a rolled-back
        # transaction this would leave Alice renamed and her custom field gone.
        with pytest.raises(Exception):
            models.update_contact(
                db, cid, 'individual', 'Renamed', custom_fields=[('Birthday', None)]
            )
        contact = models.get_contact(db, cid)
        assert contact['name'] == 'Alice'
        cfs = models.get_custom_fields(db, cid)
        assert any(cf['field_name'] == 'Phone2' for cf in cfs)

    def test_duplicate_field_name_rejected(self, db):
        with pytest.raises(ValueError):
            models.create_contact(
                db, 'individual', 'X',
                custom_fields=[('Phone', '1'), ('phone', '2')],
            )


class TestLetterBucketConsistency:
    def test_bucket_and_filter_agree(self, db):
        # Whatever bucket get_letter_counts reports a name under, clicking that
        # letter must return it. Accented initials fold to their base letter
        # ('Élodie' -> 'E', CL-0014); non-Latin initials fall under '#'.
        models.create_contact(db, 'individual', 'Élodie')  # -> 'E'
        models.create_contact(db, 'individual', '你好')      # -> '#'
        counts = models.get_letter_counts(db)
        assert counts.get('E') == 1
        assert counts.get('#') == 1
        assert 'É' not in counts and 'é' not in counts
        # count and filter agree for every bucket
        for bucket, cnt in counts.items():
            _, total = models.list_contacts(db, letter=bucket)
            assert total == cnt, f'bucket {bucket!r}: count {cnt} != filter {total}'


class TestContactPhotos:
    def test_set_and_get_ext(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        models.set_contact_photo(db, cid, 'png')
        assert models.get_contact_photo_ext(db, cid) == 'png'

    def test_set_is_upsert(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        models.set_contact_photo(db, cid, 'png')
        models.set_contact_photo(db, cid, 'jpg')
        assert models.get_contact_photo_ext(db, cid) == 'jpg'

    def test_get_none_when_absent(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        assert models.get_contact_photo_ext(db, cid) is None

    def test_clear_returns_old_ext_and_removes_row(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        models.set_contact_photo(db, cid, 'gif')
        assert models.clear_contact_photo(db, cid) == 'gif'
        assert models.get_contact_photo_ext(db, cid) is None

    def test_clear_when_absent_returns_none(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        assert models.clear_contact_photo(db, cid) is None

    def test_cascade_on_contact_delete(self, db):
        cid = models.create_contact(db, 'individual', 'Alice')
        models.set_contact_photo(db, cid, 'png')
        models.delete_contact(db, cid)
        assert models.get_contact_photo_ext(db, cid) is None

    def test_list_contacts_has_photo_flag(self, db):
        with_photo = models.create_contact(db, 'individual', 'Alice')
        models.create_contact(db, 'individual', 'Bob')
        models.set_contact_photo(db, with_photo, 'png')
        results, total = models.list_contacts(db)
        # has_photo is 1 only for the contact with a photo row; total not inflated.
        assert total == 2
        by_id = {r['id']: r['has_photo'] for r in results}
        assert by_id[with_photo] == 1
        assert all(v == 0 for k, v in by_id.items() if k != with_photo)


class TestUpcomingBirthdays:
    """CL-0038: surface contacts whose 'birthday' custom field is near."""

    def _mk(self, db, name, bday):
        return models.create_contact(
            db, 'individual', name, custom_fields=[('birthday', bday)]
        )

    def test_full_date_gives_days_and_age(self, db):
        today = datetime.date(2026, 3, 10)
        self._mk(db, 'Alice', '1990-03-14')
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert len(rows) == 1
        r = rows[0]
        assert r['name'] == 'Alice'
        assert r['days_until'] == 4
        assert r['age'] == 36
        assert (r['month'], r['day']) == (3, 14)

    def test_mmdd_has_no_age(self, db):
        today = datetime.date(2026, 3, 10)
        self._mk(db, 'Bob', '03-14')
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert rows[0]['age'] is None

    def test_birthday_today_is_included(self, db):
        today = datetime.date(2026, 3, 14)
        self._mk(db, 'Cara', '03-14')
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert rows[0]['days_until'] == 0

    def test_year_wraps_december_to_january(self, db):
        today = datetime.date(2026, 12, 28)
        self._mk(db, 'Dan', '01-02')
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert len(rows) == 1
        assert rows[0]['days_until'] == 5

    def test_outside_window_excluded(self, db):
        today = datetime.date(2026, 3, 10)
        self._mk(db, 'Eve', '05-01')
        assert models.upcoming_birthdays(db, within_days=30, today=today) == []

    def test_window_boundary_is_inclusive(self, db):
        today = datetime.date(2026, 3, 10)
        self._mk(db, 'Fay', '04-09')  # exactly 30 days out
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert len(rows) == 1 and rows[0]['days_until'] == 30

    def test_invalid_values_skipped(self, db):
        today = datetime.date(2026, 3, 10)
        self._mk(db, 'Bad', 'not-a-date')
        self._mk(db, 'Empty', '')
        self._mk(db, 'Impossible', '13-40')
        assert models.upcoming_birthdays(db, within_days=30, today=today) == []

    def test_sorted_by_days_until(self, db):
        today = datetime.date(2026, 3, 10)
        self._mk(db, 'Later', '03-25')
        self._mk(db, 'Sooner', '03-12')
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert [r['name'] for r in rows] == ['Sooner', 'Later']

    def test_leap_day_celebrated_feb28_in_non_leap_year(self, db):
        today = datetime.date(2027, 2, 1)  # 2027 is not a leap year
        self._mk(db, 'Leap', '2000-02-29')
        rows = models.upcoming_birthdays(db, within_days=30, today=today)
        assert len(rows) == 1
        assert rows[0]['next_date'] == datetime.date(2027, 2, 28)
        assert rows[0]['age'] == 27

    def test_contact_without_birthday_ignored(self, db):
        today = datetime.date(2026, 3, 10)
        models.create_contact(db, 'individual', 'NoBday')
        assert models.upcoming_birthdays(db, within_days=30, today=today) == []
