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
