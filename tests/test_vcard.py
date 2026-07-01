"""Tests for the hand-rolled vCard parser/emitter (CL-0023)."""

from __future__ import annotations

import vcard


def _one(text):
    cards = vcard.parse(text)
    assert len(cards) == 1
    return cards[0]


class TestEmit:
    def test_individual_has_fn_and_n(self):
        out = vcard.emit([{'type': 'individual', 'name': 'Alice Smith',
                           'email': 'a@b.com', 'phone': '555-1', 'notes': None,
                           'custom_fields': []}])
        assert 'BEGIN:VCARD' in out and 'END:VCARD' in out
        assert 'VERSION:3.0' in out
        assert 'FN:Alice Smith' in out
        assert 'N:Alice Smith;;;;' in out
        assert 'EMAIL:a@b.com' in out
        assert 'TEL:555-1' in out

    def test_company_has_org(self):
        out = vcard.emit([{'type': 'company', 'name': 'Acme Inc',
                           'email': None, 'phone': None, 'notes': None,
                           'custom_fields': []}])
        assert 'ORG:Acme Inc' in out
        # No structured N property for a company (guard against VERSION's 'N:').
        assert not any(ln.startswith('N:') for ln in out.splitlines())

    def test_custom_field_as_x_cl(self):
        out = vcard.emit([{'type': 'individual', 'name': 'Bob', 'email': None,
                           'phone': None, 'notes': None,
                           'custom_fields': [('Work Email', 'w@co.com')]}])
        assert 'X-CL;X-LABEL=Work Email:w@co.com' in out


class TestRoundTrip:
    def test_full_contact_roundtrips(self):
        original = {'type': 'individual', 'name': 'Carol Jones',
                    'email': 'c@x.com', 'phone': '555-9',
                    'notes': 'a note',
                    'custom_fields': [('Nickname', 'CJ'), ('City', 'Cape Town')]}
        card = _one(vcard.emit([original]))
        assert card['name'] == 'Carol Jones'
        assert card['type'] == 'individual'
        assert card['email'] == 'c@x.com'
        assert card['phone'] == '555-9'
        assert card['notes'] == 'a note'
        assert set(card['custom_fields']) == {('Nickname', 'CJ'), ('City', 'Cape Town')}

    def test_numbered_extra_roundtrips_as_custom_field(self):
        # A second email stored as an 'Email 2' custom field must come back as a
        # custom field, not a second primary EMAIL (INV-2).
        original = {'type': 'individual', 'name': 'Dave', 'email': 'd1@x.com',
                    'phone': None, 'notes': None,
                    'custom_fields': [('Email 2', 'd2@x.com')]}
        card = _one(vcard.emit([original]))
        assert card['email'] == 'd1@x.com'
        assert ('Email 2', 'd2@x.com') in card['custom_fields']

    def test_special_chars_escape_roundtrip(self):
        original = {'type': 'individual', 'name': 'Semi; Colon',
                    'email': None, 'phone': None,
                    'notes': 'Hello, world; two\nlines',
                    'custom_fields': []}
        card = _one(vcard.emit([original]))
        assert card['name'] == 'Semi; Colon'
        assert card['notes'] == 'Hello, world; two\nlines'


class TestParse:
    def test_multiple_emails_extra_becomes_custom_field(self):
        text = (
            'BEGIN:VCARD\nVERSION:3.0\nFN:Multi\n'
            'EMAIL:first@x.com\nEMAIL;TYPE=work:second@x.com\n'
            'TEL:555-1\nTEL:555-2\nEND:VCARD\n'
        )
        card = _one(text)
        assert card['email'] == 'first@x.com'
        assert card['phone'] == '555-1'
        cf = dict(card['custom_fields'])
        assert cf.get('Email 2') == 'second@x.com'
        assert cf.get('Phone 2') == '555-2'

    def test_card_with_no_name_is_skipped(self):
        text = 'BEGIN:VCARD\nVERSION:3.0\nEMAIL:x@y.com\nEND:VCARD\n'
        assert vcard.parse(text) == []

    def test_name_from_n_when_no_fn(self):
        text = 'BEGIN:VCARD\nVERSION:3.0\nN:Smith;John;;;\nEND:VCARD\n'
        card = _one(text)
        assert 'John' in card['name'] and 'Smith' in card['name']

    def test_company_detected_from_org_without_n(self):
        text = 'BEGIN:VCARD\nVERSION:3.0\nFN:Acme\nORG:Acme\nEND:VCARD\n'
        assert _one(text)['type'] == 'company'

    def test_kind_org_is_company(self):
        text = 'BEGIN:VCARD\nVERSION:4.0\nFN:Globex\nKIND:org\nEND:VCARD\n'
        assert _one(text)['type'] == 'company'

    def test_individual_with_org_and_name_is_individual(self):
        text = 'BEGIN:VCARD\nVERSION:3.0\nFN:Jane Doe\nN:Doe;Jane;;;\nORG:BigCo\nEND:VCARD\n'
        assert _one(text)['type'] == 'individual'

    def test_empty_file_yields_nothing(self):
        assert vcard.parse('') == []

    def test_line_unfolding(self):
        # A continuation line (leading space) is joined to the previous line.
        text = 'BEGIN:VCARD\nVERSION:3.0\nFN:Very Long\n NoteName\nEND:VCARD\n'
        card = _one(text)
        assert card['name'] == 'Very LongNoteName'
