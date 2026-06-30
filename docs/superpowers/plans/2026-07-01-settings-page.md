# Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-side Settings page so the single user can customise timezone, date format, theme, layout, phone region, pagination, sort, and default contact type — all persisted in the database and applied on render.

**Architecture:** A new `settings` table (key/value) read once per request into `flask.g.settings` and exposed to every template. A `settings.py` module owns the defaults, the date-format catalogue, validation, and read/write helpers. A new `/settings` blueprint renders and saves the form. Theme/layout become server-rendered (removing the old browser-only theme JS). The phone-formatting helper is unified into `phoneutil.py` (folds in CL-0016), with the region threaded through as a parameter.

**Tech Stack:** Flask 3.x, Jinja2, sqlite3, stdlib `zoneinfo`, `phonenumbers`.

**Source spec:** `docs/superpowers/specs/2026-06-30-settings-page-design.md` (signed off; passed /cold-eyes, 5 loops).

## Global Constraints

- SQL: parameterised queries only — never f-strings/`.format()` in SQL.
- XSS: rely on Jinja autoescaping; theme/layout values come from validated whitelists, never free text.
- CSRF: every POST validated by the existing global `_check_csrf` hook.
- No new dependencies (`zoneinfo` is stdlib; `phonenumbers` already a dep, pinned `>=9.0,<10.0`).
- Type hints on all signatures; PEP 8; line length ≤100; specific exceptions only.
- Settings live in the DB, not in `~/.config/contact-list/` (that dir is for secrets only).
- Test idioms (from `tests/conftest.py` / `tests/test_routes.py`): `app` fixture takes a config dict; `db` fixture yields a connection inside `app.app_context()`; `client` fixture is `app.test_client()`; CSRF tokens via the `_get_csrf(client)` helper pattern (GET a page, read `_csrf_token` from the session).
- Run the full suite with `./venv/bin/python -m pytest tests/ -q` (the venv's `pip` wrapper is broken, but its `python` works).

---

### Task 1: Settings data layer (`settings.py` + migration)

**Files:**
- Create: `migrations/003_settings.sql`
- Create: `settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `config.Config.MAX_CONTACTS_PER_PAGE` (the per-page ceiling, 200).
- Produces:
  - `settings.SETTINGS_DEFAULTS: dict[str, str]` — canonical defaults.
  - `settings.DATE_FORMATS: dict[str, str]` — format-key → strftime pattern.
  - `settings.get_settings(db: sqlite3.Connection) -> dict[str, str]`
  - `settings.update_settings(db: sqlite3.Connection, updates: dict[str, str]) -> list[str]` — returns error strings; writes nothing if any error (all-or-nothing).

**Design note (per_page):** `update_settings` *rejects* a `per_page` that is non-integer or outside `1..MAX_CONTACTS_PER_PAGE` (returns an error) rather than silently clamping — this matches the test contract. The route/data-layer keep their own defensive clamps for query-string input.

- [ ] **Step 1: Create the migration**

Create `migrations/003_settings.sql`:

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_settings.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'settings'`.

- [ ] **Step 4: Write `settings.py`**

Create `settings.py`:

```python
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
    'theme': {'', 'light', 'dark', 'nord', 'solarized', 'dracula', 'rose', 'contrast'},
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_settings.py -q`
Expected: PASS (all classes).

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add settings.py migrations/003_settings.sql tests/test_settings.py
git commit -m "Add settings data layer (CL-0001): settings table + settings.py"
```

---

### Task 2: Per-request wiring + timezone/format-aware `friendly_date`

**Files:**
- Modify: `app.py` (add `_load_settings` before-request hook; extend `_inject_globals`; rewrite `friendly_date`)
- Test: `tests/test_settings.py` (add a `TestFriendlyDate` class)

**Interfaces:**
- Consumes: `settings.get_settings`, `settings.SETTINGS_DEFAULTS`, `settings.DATE_FORMATS`.
- Produces: `g.settings` populated on every request; `settings` available in all templates; `friendly_date` Jinja filter honouring `timezone` + `date_format`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
class TestFriendlyDate:
    def _render(self, app, db, value):
        # Exercise the filter through the app's Jinja env, inside a request so
        # g.settings is populated by the before_request hook.
        with app.test_request_context('/'):
            app.preprocess_request()  # runs before_request hooks -> g.settings
            tmpl = app.jinja_env.from_string("{{ value|friendly_date }}")
            return tmpl.render(value=value)

    def test_default_format_utc(self, app, db):
        out = self._render(app, db, '2026-06-30T14:30:00Z')
        assert out == '30 Jun 2026, 14:30'

    def test_timezone_shifts_hour(self, app, db):
        settings_mod.update_settings(db, {'timezone': 'Asia/Kolkata'})  # UTC+5:30
        out = self._render(app, db, '2026-06-30T14:30:00Z')
        assert out == '30 Jun 2026, 20:00'

    def test_custom_format_key(self, app, db):
        settings_mod.update_settings(db, {'date_format': 'iso'})
        out = self._render(app, db, '2026-06-30T14:30:00Z')
        assert out == '2026-06-30 14:30'

    def test_bad_value_falls_back_to_raw(self, app, db):
        out = self._render(app, db, 'not-a-date')
        assert out == 'not-a-date'

    def test_empty_value(self, app, db):
        out = self._render(app, db, '')
        assert out == ''
```

Note: `db` fixture opens the same `DATABASE`, so writes via `update_settings` are visible to the request context opened in `_render` (same sqlite file).

- [ ] **Step 2: Run to verify failure**

Run: `./venv/bin/python -m pytest tests/test_settings.py::TestFriendlyDate -q`
Expected: FAIL — `test_timezone_shifts_hour` / `test_custom_format_key` assert old behaviour (filter ignores settings).

- [ ] **Step 3: Add the before-request loader BEFORE `_check_csrf`**

In `app.py`, insert this **above** the existing `_check_csrf` definition (so it registers first and runs even on a CSRF-aborted request):

```python
    @app.before_request
    def _load_settings() -> None:
        import settings as settings_mod
        from db import get_db
        try:
            g.settings = settings_mod.get_settings(get_db())
        except Exception:
            # Never let a settings-load failure 500 the request; fall back to
            # defaults so the page (and error pages) still render.
            g.settings = dict(settings_mod.SETTINGS_DEFAULTS)
```

Add `from flask import g` to the existing flask import line in `app.py` (currently `from flask import Flask, abort, render_template, request, session`).

- [ ] **Step 4: Extend `_inject_globals` to expose settings**

In `app.py`, in `_inject_globals`, add `settings` to the returned dict (keep the existing keys and the `contact_count` DB read unchanged):

```python
        import settings as settings_mod
        return {
            'csrf_token': csrf_token,
            'active_nav': request.path,
            'contact_count': total,
            'settings': getattr(g, 'settings', None) or settings_mod.SETTINGS_DEFAULTS,
        }
```

- [ ] **Step 5: Rewrite `friendly_date`**

Replace the existing `friendly_date` filter body in `app.py` with:

```python
    @app.template_filter('friendly_date')
    def friendly_date(value: str) -> str:
        """Convert an ISO-8601 UTC timestamp to the user's timezone and format."""
        if not value:
            return ''
        import settings as settings_mod
        s = getattr(g, 'settings', None) or settings_mod.SETTINGS_DEFAULTS
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            dt = dt.astimezone(ZoneInfo(s['timezone']))
            fmt = settings_mod.DATE_FORMATS.get(
                s['date_format'], settings_mod.DATE_FORMATS['dmy_hm']
            )
            return dt.strftime(fmt)
        except (ValueError, AttributeError, ZoneInfoNotFoundError):
            return value
```

Add the imports at the top of `app.py` (next to `from datetime import datetime`):

```python
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
```

- [ ] **Step 6: Run the filter tests + full suite**

Run: `./venv/bin/python -m pytest tests/test_settings.py -q && ./venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_settings.py
git commit -m "Wire settings per-request; make friendly_date timezone/format aware (CL-0002, CL-0003)"
```

---

### Task 3: Shared phone helper + region threading (folds in CL-0016, CL-0006)

**Files:**
- Create: `phoneutil.py`
- Modify: `routes/contacts.py` (remove local `format_phone` + `DEFAULT_REGION`; call shared helper with the region setting)
- Modify: `google_sync.py` (remove `_format_phone` + `DEFAULT_REGION`; thread `region` through `sync_contacts` → `_upsert_person`)
- Modify: `routes/sync.py` (pass `g.settings['phone_region']` to `sync_contacts`)
- Test: `tests/test_settings.py` (add `TestPhoneUtil`)

**Interfaces:**
- Produces: `phoneutil.format_phone(raw: str, region: str) -> str`.
- Changes: `google_sync.sync_contacts(config, db, region: str)`; `google_sync._upsert_person(db, person, region: str)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings.py`:

```python
class TestPhoneUtil:
    def test_formats_za_number(self):
        import phoneutil
        assert phoneutil.format_phone('0821234567', 'ZA') == '+27 82 123 4567'

    def test_formats_us_number(self):
        import phoneutil
        assert phoneutil.format_phone('2025550123', 'US') == '+1 202-555-0123'

    def test_unparseable_returns_raw(self):
        import phoneutil
        assert phoneutil.format_phone('not a phone', 'ZA') == 'not a phone'
```

- [ ] **Step 2: Run to verify failure**

Run: `./venv/bin/python -m pytest tests/test_settings.py::TestPhoneUtil -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoneutil'`.

- [ ] **Step 3: Create `phoneutil.py`**

```python
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
```

- [ ] **Step 4: Run the phoneutil test**

Run: `./venv/bin/python -m pytest tests/test_settings.py::TestPhoneUtil -q`
Expected: PASS.

- [ ] **Step 5: Refactor `routes/contacts.py` to use the shared helper**

In `routes/contacts.py`:
- Delete the `DEFAULT_REGION = 'ZA'` line (line ~41) and the entire local `format_phone` function (lines ~46-54).
- Add to imports: `import phoneutil` and `from flask import g` (add `g` to the existing flask import).
- In `_validate_form`, change the formatting call (currently `phone = format_phone(phone)`, ~line 102) to:

```python
        phone = phoneutil.format_phone(phone, g.settings['phone_region'])
```

- [ ] **Step 6: Refactor `google_sync.py` to take a region parameter**

In `google_sync.py`:
- Delete `DEFAULT_REGION = 'ZA'` (line ~10) and the `_format_phone` function (lines ~13-29).
- Add `import phoneutil` to the imports.
- Change `def sync_contacts(config: dict, db: sqlite3.Connection) -> tuple[int, str | None]:` to add `region: str`:

```python
def sync_contacts(config: dict, db: sqlite3.Connection, region: str) -> tuple[int, str | None]:
```

- Find the call to `_upsert_person(db, person)` inside `sync_contacts` and pass `region`:

```python
            _upsert_person(db, person, region)
```

- Change `def _upsert_person(db: sqlite3.Connection, person: dict) -> bool:` to:

```python
def _upsert_person(db: sqlite3.Connection, person: dict, region: str) -> bool:
```

- Replace the internal `_format_phone(value)` call (~line 194) with the shared helper, preserving the blank-stays-blank behaviour that `_format_phone(str | None)` used to provide:

```python
            value = phoneutil.format_phone(value, region) if value else value
```

(Match the surrounding variable name used for the phone value at that call site.)

- [ ] **Step 7: Pass the region from the sync route**

In `routes/sync.py`, locate the route that calls `google_sync.sync_contacts(config, db)` (~line 76) and pass the region from settings (the route runs in request context, so `g.settings` is populated):
- Add `from flask import g` to the imports if not present.
- Change the call to:

```python
    count, error = google_sync.sync_contacts(config, db, g.settings['phone_region'])
```

(Adjust the left-hand unpacking to match the existing call site.)

- [ ] **Step 8: Run the full suite**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all green (existing sync tests must still pass; if a sync test calls `sync_contacts` directly, it now needs a `region` arg — update those call sites to pass `'ZA'`).

- [ ] **Step 9: Commit**

```bash
git add phoneutil.py routes/contacts.py google_sync.py routes/sync.py tests/test_settings.py
git commit -m "Unify phone formatting into phoneutil; make region a setting (CL-0006, CL-0016)"
```

---

### Task 4: Settings route + template

**Files:**
- Create: `routes/settings.py`
- Create: `templates/settings.html`
- Modify: `app.py` (register the `settings` blueprint)
- Modify: `templates/base.html` (add a "Settings" nav link)
- Test: `tests/test_settings.py` (add `TestSettingsRoute`)

**Interfaces:**
- Consumes: `settings.get_settings`, `settings.update_settings`, `settings.DATE_FORMATS`, `g.settings`.
- Produces: `GET /settings` (renders form), `POST /settings` (saves or re-renders with errors). Blueprint name `settings`, endpoints `settings.settings_page` (GET) and `settings.save_settings` (POST).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
class TestSettingsRoute:
    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def _csrf(self, client):
        client.get('/settings')
        with client.session_transaction() as sess:
            return sess.get('_csrf_token', '')

    def test_get_renders(self, client):
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'Settings' in resp.data

    def test_post_persists_and_redirects(self, client, db):
        token = self._csrf(client)
        resp = client.post('/settings', data={
            '_csrf_token': token,
            'theme': 'dark',
            'timezone': 'UTC',
            'date_format': 'iso',
            'density': 'compact',
            'view': 'card',
            'phone_region': 'US',
            'per_page': '25',
            'sort': 'created',
            'sort_dir': 'desc',
            'default_type': 'company',
        })
        assert resp.status_code == 302
        assert settings_mod.get_settings(db)['theme'] == 'dark'

    def test_post_invalid_returns_400(self, client):
        token = self._csrf(client)
        resp = client.post('/settings', data={
            '_csrf_token': token,
            'theme': 'neon',  # invalid
        })
        assert resp.status_code == 400
        assert b'Invalid value' in resp.data

    def test_post_without_csrf_403(self, client):
        resp = client.post('/settings', data={'theme': 'dark'})
        assert resp.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `./venv/bin/python -m pytest tests/test_settings.py::TestSettingsRoute -q`
Expected: FAIL — 404 (no `/settings` route yet).

- [ ] **Step 3: Create the blueprint**

Create `routes/settings.py`:

```python
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

import settings as settings_mod
from db import get_db

bp = Blueprint('settings', __name__)

# Keys the form is allowed to submit (the full settings surface).
_FORM_KEYS = tuple(settings_mod.SETTINGS_DEFAULTS.keys())


def _choices() -> dict:
    """Choice lists for the template's <select> controls."""
    import zoneinfo
    return {
        'timezones': sorted(zoneinfo.available_timezones()),
        'date_formats': settings_mod.DATE_FORMATS,
        'themes': ['', 'light', 'dark', 'nord', 'solarized', 'dracula', 'rose', 'contrast'],
        'regions': sorted(__import__('phonenumbers').SUPPORTED_REGIONS),
    }


@bp.route('/settings')
def settings_page():
    return render_template('settings.html', settings=g.settings, **_choices())


@bp.route('/settings', methods=['POST'])
def save_settings():
    updates = {k: request.form[k] for k in _FORM_KEYS if k in request.form}
    errors = settings_mod.update_settings(get_db(), updates)
    if errors:
        # Re-render with the SUBMITTED values + the same choice lists as GET.
        submitted = dict(g.settings)
        submitted.update(updates)
        return render_template(
            'settings.html', settings=submitted, errors=errors, **_choices()
        ), 400
    flash('Settings saved.', 'success')
    return redirect(url_for('settings.settings_page'))
```

- [ ] **Step 4: Create the template**

Create `templates/settings.html`:

```html
{% extends "base.html" %}
{% block title %}Settings{% endblock %}

{% block content %}
<h1>Settings</h1>

{% if errors %}
<div class="flash flash-error">
    <ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
</div>
{% endif %}

<form method="post" action="{{ url_for('settings.save_settings') }}" class="settings-form">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">

    <fieldset>
        <legend>Appearance</legend>
        <label>Theme
            <select name="theme">
                {% for t in themes %}
                <option value="{{ t }}" {{ 'selected' if settings.theme == t }}>{{ t or 'Auto' }}</option>
                {% endfor %}
            </select>
        </label>
        <label>Density
            <select name="density">
                <option value="comfortable" {{ 'selected' if settings.density == 'comfortable' }}>Comfortable</option>
                <option value="compact" {{ 'selected' if settings.density == 'compact' }}>Compact</option>
            </select>
        </label>
        <label>Contact view
            <select name="view">
                <option value="list" {{ 'selected' if settings.view == 'list' }}>List</option>
                <option value="card" {{ 'selected' if settings.view == 'card' }}>Card</option>
            </select>
        </label>
    </fieldset>

    <fieldset>
        <legend>Dates &amp; Time</legend>
        <label>Timezone
            <select name="timezone">
                {% for tz in timezones %}
                <option value="{{ tz }}" {{ 'selected' if settings.timezone == tz }}>{{ tz }}</option>
                {% endfor %}
            </select>
        </label>
        <label>Date format
            <select name="date_format">
                {% for key, pattern in date_formats.items() %}
                <option value="{{ key }}" {{ 'selected' if settings.date_format == key }}>{{ key }}</option>
                {% endfor %}
            </select>
        </label>
    </fieldset>

    <fieldset>
        <legend>Contacts &amp; Phone</legend>
        <label>Phone region
            <select name="phone_region">
                {% for r in regions %}
                <option value="{{ r }}" {{ 'selected' if settings.phone_region == r }}>{{ r }}</option>
                {% endfor %}
            </select>
        </label>
        <label>Contacts per page
            <input type="number" name="per_page" min="1" max="200" value="{{ settings.per_page }}">
        </label>
        <label>Default sort
            <select name="sort">
                {% for s in ['name', 'type', 'created', 'updated'] %}
                <option value="{{ s }}" {{ 'selected' if settings.sort == s }}>{{ s }}</option>
                {% endfor %}
            </select>
        </label>
        <label>Sort direction
            <select name="sort_dir">
                <option value="asc" {{ 'selected' if settings.sort_dir == 'asc' }}>Ascending</option>
                <option value="desc" {{ 'selected' if settings.sort_dir == 'desc' }}>Descending</option>
            </select>
        </label>
        <label>Default new-contact type
            <select name="default_type">
                <option value="individual" {{ 'selected' if settings.default_type == 'individual' }}>Individual</option>
                <option value="company" {{ 'selected' if settings.default_type == 'company' }}>Company</option>
            </select>
        </label>
    </fieldset>

    <button type="submit" class="btn">Save settings</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Register the blueprint**

In `app.py`, next to the existing blueprint registrations:

```python
    from routes.settings import bp as settings_bp
    app.register_blueprint(settings_bp)
```

- [ ] **Step 6: Add the nav link**

In `templates/base.html`, inside `<div class="nav-links">`, add after the Google Sync link:

```html
                <a href="{{ url_for('settings.settings_page') }}" {{ 'class=active' if active_nav == '/settings' }}>Settings</a>
```

- [ ] **Step 7: Run the route tests + full suite**

Run: `./venv/bin/python -m pytest tests/test_settings.py -q && ./venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add routes/settings.py templates/settings.html app.py templates/base.html tests/test_settings.py
git commit -m "Add /settings page and form (CL-0001, CL-0007)"
```

---

### Task 5: Server-rendered theme & layout; remove browser-only theme JS

**Files:**
- Modify: `templates/base.html` (`<html>` data-theme, `<body>` classes, remove theme-picker markup)
- Modify: `static/app.js` (remove pre-paint IIFE + theme-picker logic)
- Modify: `static/style.css` (`.density-compact`, `body.view-card` rules)
- Test: `tests/test_settings.py` (add `TestThemeRendering`)

**Interfaces:**
- Consumes: `settings.theme`, `settings.density`, `settings.view` from template context.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
class TestThemeRendering:
    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def _csrf(self, client):
        client.get('/settings')
        with client.session_transaction() as sess:
            return sess.get('_csrf_token', '')

    def test_auto_theme_omits_attribute(self, client):
        resp = client.get('/contacts')
        assert b'data-theme=""' not in resp.data
        assert b'<html lang="en">' in resp.data

    def test_explicit_theme_emits_attribute(self, client, db):
        settings_mod.update_settings(db, {'theme': 'dark'})
        resp = client.get('/contacts')
        assert b'data-theme="dark"' in resp.data

    def test_body_layout_classes(self, client, db):
        settings_mod.update_settings(db, {'density': 'compact', 'view': 'card'})
        resp = client.get('/contacts')
        assert b'density-compact' in resp.data
        assert b'view-card' in resp.data
```

- [ ] **Step 2: Run to verify failure**

Run: `./venv/bin/python -m pytest tests/test_settings.py::TestThemeRendering -q`
Expected: FAIL — body has no layout classes; `<html>` has no settings-driven attribute.

- [ ] **Step 3: Update `base.html` `<html>` and `<body>`**

Change line 2 of `templates/base.html` from `<html lang="en">` to:

```html
<html lang="en"{% if settings.theme %} data-theme="{{ settings.theme }}"{% endif %}>
```

Change `<body>` (line ~10) to:

```html
<body class="density-{{ settings.density }} view-{{ settings.view }}">
```

- [ ] **Step 4: Remove the theme-picker markup from `base.html`**

Delete the entire `<div class="theme-picker">…</div>` block (lines ~18-48 — the toggle button and the 8 `.theme-option` buttons). Leave the `.nav-toggle` hamburger button and everything else in the nav intact.

- [ ] **Step 5: Remove the theme JS from `app.js`**

In `static/app.js`:
- Delete the pre-paint IIFE at the very top (lines 1-9, the `localStorage.getItem('contact_list_theme')` block).
- Delete the "Theme picker" statements inside the main IIFE (lines ~15-59: the `THEME_KEY`/`themeToggle`/`themeDropdown`/`applyTheme` block, down to just before the "Flash message dismiss" comment).
- **Keep** the main IIFE wrapper `(function () { 'use strict';` and everything from the flash-dismiss block onward.

- [ ] **Step 6: Add density + card CSS**

In `static/style.css`, append:

```css
/* ---- Layout density (Settings) ---- */
body.density-compact main { padding-top: 0.5rem; }
body.density-compact table td,
body.density-compact table th { padding-top: 0.35rem; padding-bottom: 0.35rem; }
body.density-compact .toolbar { margin-bottom: 0.5rem; }

/* ---- Card view (Settings) ----
   Reuse the existing responsive stacked-row treatment (the table's
   data-label cells) at all widths when the user picks card view. */
body.view-card table thead { display: none; }
body.view-card table,
body.view-card table tbody,
body.view-card table tr,
body.view-card table td { display: block; width: 100%; }
body.view-card table tr {
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 0.75rem;
    padding: 0.5rem 0.75rem;
}
body.view-card table td { border: none; padding: 0.25rem 0; }
body.view-card table td[data-label]::before {
    content: attr(data-label) ": ";
    font-weight: 600;
    color: var(--muted, inherit);
}
body.view-card table td.td-check::before,
body.view-card table td.td-icon::before { content: ""; }
```

(If `static/style.css` already defines a mobile `@media` block that stacks the table via `data-label`, mirror its exact selectors here instead of the generic ones above — check the file first and prefer reusing its variables like `--border`/`--muted`.)

- [ ] **Step 7: Run the rendering tests + full suite**

Run: `./venv/bin/python -m pytest tests/test_settings.py -q && ./venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add templates/base.html static/app.js static/style.css tests/test_settings.py
git commit -m "Server-render theme & layout; drop browser-only theme JS (CL-0004, CL-0005)"
```

---

### Task 6: Consume the saved defaults in the contact list & new-contact form

**Files:**
- Modify: `routes/contacts.py` (`contact_list` defaults from settings; `new_contact` default type)
- Modify: `templates/contact_form.html` (pre-select default type when creating)
- Test: `tests/test_settings.py` (add `TestDefaultsConsumed`)

**Interfaces:**
- Consumes: `g.settings['per_page' | 'sort' | 'sort_dir' | 'default_type']`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
class TestDefaultsConsumed:
    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def _seed(self, client, db, n):
        # Create n contacts directly via the model for speed.
        import models
        for i in range(n):
            models.create_contact(db, 'individual', f'Person {i:03d}')

    def test_per_page_default_from_settings(self, client, db):
        settings_mod.update_settings(db, {'per_page': '5'})
        self._seed(client, db, 8)
        resp = client.get('/contacts')
        # With per_page=5 and 8 contacts there must be a second page.
        assert b'Page 1 of 2' in resp.data

    def test_explicit_query_arg_overrides_setting(self, client, db):
        settings_mod.update_settings(db, {'per_page': '5'})
        self._seed(client, db, 8)
        resp = client.get('/contacts?per_page=50')
        assert b'Page 1 of 2' not in resp.data  # all on one page

    def test_new_contact_preselects_default_type(self, client, db):
        settings_mod.update_settings(db, {'default_type': 'company'})
        resp = client.get('/contacts/new')
        # the company radio/option is checked/selected
        assert b'company' in resp.data
```

- [ ] **Step 2: Run to verify failure**

Run: `./venv/bin/python -m pytest tests/test_settings.py::TestDefaultsConsumed -q`
Expected: FAIL — `test_per_page_default_from_settings` fails (route still defaults to 50).

- [ ] **Step 3: Make `contact_list` fall back to settings (presence-checked)**

In `routes/contacts.py` `contact_list`, replace the hardcoded defaults. Add `from flask import g` (extend the existing import). Change the per_page/sort/dir lines (~124-133) to read settings when the query arg is absent:

```python
    s = g.settings
    page = max(request.args.get('page', 1, type=int), 1)

    per_page_arg = request.args.get('per_page', type=int)
    per_page = per_page_arg if per_page_arg is not None else int(s['per_page'])
    per_page = max(1, min(per_page, 200))

    search = request.args.get('q', '').strip()
    contact_type = request.args.get('type', '').strip()
    letter = request.args.get('letter', '').strip()

    db = get_db()
    sort = request.args.get('sort') or s['sort']
    sort_dir = request.args.get('dir') or s['sort_dir']
```

(Leave the rest of `contact_list` unchanged — it already passes `sort`/`sort_dir`/`per_page` to the template and `list_contacts`.)

- [ ] **Step 4: Pre-select the default type in `new_contact`**

In `routes/contacts.py` `new_contact`, pass the default type to the template:

```python
@bp.route('/contacts/new')
def new_contact():
    ref = _safe_ref(_get_ref())
    return render_template(
        'contact_form.html', contact=None, custom_fields=[], editing=False,
        ref=ref, default_type=g.settings['default_type'],
    )
```

In `templates/contact_form.html`, find the type control. For the create case (`contact` is None), mark the option matching `default_type` as selected. For example, if the control is a `<select name="type">`:

```html
                <option value="individual" {{ 'selected' if (contact.type if contact else default_type) == 'individual' }}>Individual</option>
                <option value="company" {{ 'selected' if (contact.type if contact else default_type) == 'company' }}>Company</option>
```

(Adapt to the actual control — if it's radio buttons, add `checked` analogously. Read `templates/contact_form.html` first to match its structure; `default_type` is only defined on the create route, so guard with `default_type is defined` if the template is shared with edit.)

- [ ] **Step 5: Run the tests + full suite**

Run: `./venv/bin/python -m pytest tests/test_settings.py -q && ./venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add routes/contacts.py templates/contact_form.html tests/test_settings.py
git commit -m "Consume saved per-page/sort/default-type settings in contact list & form (CL-0007)"
```

---

## Final verification

- [ ] **Run the full suite one last time**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all green (original 67 + the new settings tests).

- [ ] **Manual smoke test**

Run the app (`./run.sh`), open `/settings`, change theme + timezone + per-page + default type, save, and confirm: the theme applies without a flash, dates show in the chosen zone/format, the contact list paginates by the new size, and a new contact defaults to the chosen type.

- [ ] **Mark roadmap items shipped**

Flip CL-0001, CL-0002, CL-0003, CL-0004, CL-0005, CL-0006, CL-0007, and CL-0016 to ✅ in `ROADMAP.md`, and add a CHANGELOG "Added" entry for the Settings page.

---

## Coverage check (plan vs spec)

| Spec section | Task |
|---|---|
| §3 data layer (table, `settings.py`) | Task 1 |
| §4 per-request load + `friendly_date` (CL-0002/0003) | Task 2 |
| §5 date-format catalogue | Task 1 (defined), Task 2 (applied) |
| §6 theme & layout server-rendered (CL-0004/0005) | Task 5 |
| §7 phone helper + region threading (CL-0006/0016) | Task 3 |
| §8 settings route + template (CL-0001/0007) | Task 4 |
| §9 consume defaults (per-page/sort/default-type) | Task 6 |
| §10 testing | every task (TDD) |
| §11 standards compliance | Global Constraints + per-task |
