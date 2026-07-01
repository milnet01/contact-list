"""Tests for the CSV parsing + column-mapping helpers (CL-0022)."""

from __future__ import annotations

import importer


class TestHeaderSignature:
    def test_stable_and_case_insensitive(self):
        assert importer.header_signature(['Name', 'Email']) == \
               importer.header_signature([' name ', 'EMAIL'])

    def test_differs_by_layout(self):
        assert importer.header_signature(['Name', 'Email']) != \
               importer.header_signature(['Email', 'Name'])


class TestSplitMultivalue:
    def test_primary_and_numbered_extras(self):
        primary, extras = importer.split_multivalue('Email', ['a@x', 'b@x', 'c@x'])
        assert primary == 'a@x'
        assert extras == [('Email 2', 'b@x'), ('Email 3', 'c@x')]

    def test_all_empty(self):
        assert importer.split_multivalue('Phone', ['', '  ']) == (None, [])


class TestParseCsv:
    def test_header_and_rows(self):
        headers, rows = importer.parse_csv('Name,Email\nAlice,a@x.com\nBob,b@x.com\n')
        assert headers == ['Name', 'Email']
        assert rows == [['Alice', 'a@x.com'], ['Bob', 'b@x.com']]

    def test_ragged_rows_preserved_for_apply(self):
        headers, rows = importer.parse_csv('A,B,C\n1,2\n1,2,3,4\n')
        assert headers == ['A', 'B', 'C']
        assert rows == [['1', '2'], ['1', '2', '3', '4']]


class TestGuessMapping:
    def test_common_aliases(self):
        m = importer.guess_mapping(['Full Name', 'E-mail Address', 'Mobile', 'Notes', 'Weird'])
        assert m[0] == 'name'
        assert m[1] == 'email'
        assert m[2] == 'phone'
        assert m[3] == 'notes'
        assert m[4] == 'ignore'


class TestApplyMapping:
    def _apply(self, headers, rows, mapping, default_type='individual'):
        return importer.apply_mapping(headers, rows, mapping, default_type)

    def test_basic_row(self):
        built, skipped = self._apply(
            ['Name', 'Email'], [['Alice', 'a@x.com']], {0: 'name', 1: 'email'}
        )
        assert skipped == 0
        fields, cfs = built[0]
        assert fields['name'] == 'Alice'
        assert fields['email'] == 'a@x.com'
        assert fields['type'] == 'individual'

    def test_two_name_columns_join(self):
        built, _ = self._apply(
            ['First', 'Last'], [['Alice', 'Smith']], {0: 'name', 1: 'name'}
        )
        assert built[0][0]['name'] == 'Alice Smith'

    def test_extra_email_column_becomes_custom_field(self):
        built, _ = self._apply(
            ['Email', 'Email2'], [['a@x.com', 'b@x.com']], {0: 'email', 1: 'email'}
        )
        fields, cfs = built[0]
        assert fields['email'] == 'a@x.com'
        assert ('Email 2', 'b@x.com') in cfs

    def test_custom_column_label_sanitised(self):
        built, _ = self._apply(
            ['Contact (work)'], [['hi']], {0: 'custom'}
        )
        # 'Contact (work)' -> sanitised 'Contact work'; but no name/email -> the
        # row still counts as data because a custom value is present? No: a row
        # with no name and no email is skipped. Give it a name column too.
        built, _ = self._apply(
            ['Name', 'Contact (work)'], [['Zoe', 'hi']], {0: 'name', 1: 'custom'}
        )
        cfs = dict(built[0][1])
        assert cfs.get('Contact work') == 'hi'

    def test_duplicate_custom_headers_disambiguated(self):
        built, _ = self._apply(
            ['Name', 'Tag', 'Tag'], [['Zoe', 'x', 'y']],
            {0: 'name', 1: 'custom', 2: 'custom'},
        )
        cfs = dict(built[0][1])
        assert cfs.get('Tag') == 'x'
        assert cfs.get('Tag 2') == 'y'

    def test_default_type_applied_when_no_type_column(self):
        built, _ = self._apply(['Name'], [['Acme']], {0: 'name'}, default_type='company')
        assert built[0][0]['type'] == 'company'

    def test_type_column_overrides_default(self):
        built, _ = self._apply(
            ['Name', 'Type'], [['Acme', 'company']], {0: 'name', 1: 'type'},
            default_type='individual',
        )
        assert built[0][0]['type'] == 'company'

    def test_blank_row_skipped(self):
        built, skipped = self._apply(
            ['Name', 'Email'], [['', ''], ['Bob', '']], {0: 'name', 1: 'email'}
        )
        assert skipped == 1
        assert len(built) == 1
        assert built[0][0]['name'] == 'Bob'

    def test_ragged_row_padded(self):
        built, _ = self._apply(
            ['Name', 'Email', 'Notes'], [['Bob']], {0: 'name', 1: 'email', 2: 'notes'}
        )
        fields = built[0][0]
        assert fields['name'] == 'Bob'
        assert fields['email'] is None
