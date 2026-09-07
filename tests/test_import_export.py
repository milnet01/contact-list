"""Tests for the CSV export/import helpers in routes/import_export.py."""

from __future__ import annotations

from routes.import_export import _csv_safe


class TestCsvSafeFormulaLeaders:
    # Why this exists: an exported field beginning with a spreadsheet formula
    # leader (=, @, tab, CR) executes when the CSV is opened in Excel or
    # LibreOffice (OWASP CSV injection / CWE-1236). The contact data is not
    # ours -- it can arrive from an imported file or a Google sync pull.
    def test_equals_leader_is_quoted(self):
        assert _csv_safe('=HYPERLINK("http://evil/","x")') == \
            "'=HYPERLINK(\"http://evil/\",\"x\")"

    def test_at_leader_is_quoted(self):
        assert _csv_safe('@SUM(1+1)') == "'@SUM(1+1)"


class TestCsvSafePhoneNumbersUnquoted:
    # Why this exists: `+`/`-` also lead every E.164 phone number and every
    # negative number. The naive fix (blanket-quote +/-) mangled the most
    # common field in the export, so the leader is narrowed to only fire when
    # what follows is not phone-/number-shaped.
    def test_international_phone_with_spaces_unchanged(self):
        assert _csv_safe('+27 82 555 0123') == '+27 82 555 0123'

    def test_international_phone_with_dashes_unchanged(self):
        assert _csv_safe('+1-555-0100') == '+1-555-0100'

    def test_negative_number_unchanged(self):
        assert _csv_safe('-1234') == '-1234'

    def test_dash_leading_text_is_quoted(self):
        assert _csv_safe('-Dash Leading') == "'-Dash Leading"
