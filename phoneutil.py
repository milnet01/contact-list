from __future__ import annotations

import phonenumbers


def format_phone(raw: str, region: str) -> str:
    """Parse and format a phone number to international format.

    Returns the raw input unchanged if it can't be parsed.
    """
    try:
        parsed = phonenumbers.parse(raw, region)
        if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
    except phonenumbers.NumberParseException:
        pass
    return raw


def normalize_e164(raw: str, region: str) -> str | None:
    """Return the E.164 form of ``raw`` (e.g. ``+12025550123``), or ``None`` if
    it can't be parsed to a valid/possible number.

    Used to compare two phone numbers for equality regardless of how they were
    typed or formatted (CL-0013).
    """
    try:
        parsed = phonenumbers.parse(raw, region)
        if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None
