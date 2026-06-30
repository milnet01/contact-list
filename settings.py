from __future__ import annotations

import sqlite3
import zoneinfo
from collections.abc import Callable

from phonenumbers import SUPPORTED_REGIONS

from config import Config

# Format-key -> strftime pattern. Keys are the stored values; patterns are
# applied in friendly_date. 'dmy_hm' is the default (matches the historical
# hardcoded format).
DATE_FORMATS: dict[str, str] = {
    'dmy_hm': '%d %b %Y, %H:%M',
    'mdy_hm': '%b %d %Y, %I:%M %p',
    'iso': '%Y-%m-%d %H:%M',
    'dmy': '%d %b %Y',
    'mdy': '%m/%d/%Y',
}

# Theme choices in UI display order: auto, light, dark, then the rest.
# This is the single source of truth — both the validator set below and
# routes/settings.py's <select> options derive from it.
THEMES: tuple[str, ...] = ('', 'light', 'dark', 'nord', 'solarized', 'dracula', 'rose', 'contrast')

SETTINGS_DEFAULTS: dict[str, str] = {
    'timezone': 'UTC',
    'date_format': 'dmy_hm',
    'theme': '',
    'density': 'comfortable',
    'view': 'list',
    'phone_region': 'ZA',
    'per_page': '50',
    'sort': 'name',
    'sort_dir': 'asc',
    'default_type': 'individual',
}

# Literal allowed-value sets for the enum-like keys.
_ALLOWED: dict[str, set[str]] = {
    'theme': set(THEMES),
    'density': {'comfortable', 'compact'},
    'view': {'list', 'card'},
    'sort': {'name', 'type', 'created', 'updated'},
    'sort_dir': {'asc', 'desc'},
    'default_type': {'individual', 'company'},
}


def _valid_per_page(value: str) -> bool:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False
    return 1 <= n <= Config.MAX_CONTACTS_PER_PAGE


def _valid_timezone(value: str) -> bool:
    return value in zoneinfo.available_timezones()


SETTINGS_VALIDATORS: dict[str, Callable[[str], bool]] = {
    'timezone': _valid_timezone,
    'date_format': lambda v: v in DATE_FORMATS,
    'phone_region': lambda v: v in SUPPORTED_REGIONS,
    'per_page': _valid_per_page,
    'theme': lambda v: v in _ALLOWED['theme'],
    'density': lambda v: v in _ALLOWED['density'],
    'view': lambda v: v in _ALLOWED['view'],
    'sort': lambda v: v in _ALLOWED['sort'],
    'sort_dir': lambda v: v in _ALLOWED['sort_dir'],
    'default_type': lambda v: v in _ALLOWED['default_type'],
}


def get_settings(db: sqlite3.Connection) -> dict[str, str]:
    """Return SETTINGS_DEFAULTS overlaid with stored rows (unknown keys ignored)."""
    result = dict(SETTINGS_DEFAULTS)
    for row in db.execute('SELECT key, value FROM settings').fetchall():
        if row['key'] in SETTINGS_DEFAULTS:
            result[row['key']] = row['value']
    return result


def update_settings(db: sqlite3.Connection, updates: dict[str, str]) -> list[str]:
    """Validate and upsert. Returns human-readable errors; writes nothing on
    any error (all-or-nothing)."""
    errors: list[str] = []
    for key, value in updates.items():
        validator = SETTINGS_VALIDATORS.get(key)
        if validator is None:
            errors.append(f'Unknown setting: {key}')
        elif not validator(value):
            errors.append(f'Invalid value for {key}: {value!r}')
    if errors:
        return errors
    for key, value in updates.items():
        db.execute(
            'INSERT INTO settings (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, value),
        )
    db.commit()
    return []
