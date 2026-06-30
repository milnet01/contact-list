# Settings Page & User Preferences — Design

**Date:** 2026-06-30
**Status:** Draft (pending cold-eyes + user review)
**Roadmap items:** CL-0001, CL-0002, CL-0003, CL-0004, CL-0005, CL-0006, CL-0007
(folds in CL-0016 — shared phone helper)

---

## Contents

1. Purpose
2. Scope
3. Data layer (schema, `settings.py` module, defense-in-depth)
4. Applying settings per request
5. Date format catalogue
6. Theme & layout (server-rendered)
7. Phone region + shared helper (folds in CL-0016)
8. UI / route
9. Consuming the new defaults
10. Testing
11. Standards compliance (DESIGN.md)
12. Risks & mitigations

---

## 1. Purpose

Add a single Settings page that lets the single user customise how the app
looks and behaves, with every preference persisted server-side (in the app
database) so it is the one source of truth and applies on every device.

This replaces several hardcoded values:

- `friendly_date` Jinja filter (`app.py`) — hardcoded `'%d %b %Y, %H:%M'`, always UTC.
- `DEFAULT_REGION = 'ZA'` — duplicated in `routes/contacts.py` and `google_sync.py`.
- `CONTACTS_PER_PAGE = 50` and the per-route sort defaults.
- Theme/layout — currently browser-only (`localStorage` in `static/app.js`).

## 2. Scope

In scope (one pass): all ten settings below — covering roadmap items
CL-0002–CL-0007 (CL-0001 is the page that hosts them) — plus the shared phone
helper. The date-format default key is `dmy_hm` (referenced in §4 and §5).

| # | Roadmap | Setting | Allowed values | Default |
|---|---------|---------|----------------|---------|
| 1 | CL-0002 | `timezone` | any IANA name in `zoneinfo.available_timezones()` | `UTC` |
| 2 | CL-0003 | `date_format` | a key from a curated `DATE_FORMATS` map (see §5) | `dmy_hm` |
| 3 | CL-0004 | `theme` | `''` (auto), `light`, `dark`, `nord`, `solarized`, `dracula`, `rose`, `contrast` | `''` |
| 4 | CL-0005 | `density` | `comfortable`, `compact` | `comfortable` |
| 5 | CL-0005 | `view` | `list`, `card` | `list` |
| 6 | CL-0006 | `phone_region` | a 2-letter region in `phonenumbers.SUPPORTED_REGIONS` | `ZA` |
| 7 | CL-0007 | `per_page` | int, clamped 1–`MAX_CONTACTS_PER_PAGE` (200) | `50` |
| 8 | CL-0007 | `sort` | `name`, `type`, `created`, `updated` (matches `list_contacts`) | `name` |
| 9 | CL-0007 | `sort_dir` | `asc`, `desc` | `asc` |
| 10 | CL-0007 | `default_type` | `individual`, `company` | `individual` |

**Setting key vs URL param:** the stored setting key for sort direction is
`sort_dir`, but the contact-list route's overriding query parameter is named
`dir` (per `DESIGN.md` §9.1 / `routes/contacts.py`). The `sort` key and the
`sort` query param share a name. See §9 for how an explicit query param
overrides the stored default.

Out of scope: multi-user settings, import/export of settings, per-contact
overrides, live theme preview without reload, and **schema-version tracking
(CL-0008)** — this spec adds one idempotent migration and does not introduce a
version table; CL-0008 remains open and independent.

## 3. Data layer

### 3.1 Schema — `migrations/003_settings.sql`

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Key/value, all values stored as TEXT. Absent key ⇒ fall back to the default.
No row is written until the user saves; defaults live in code (§3.2), so a
fresh database behaves identically to a saved-all-defaults one.

**Deviation from `DESIGN.md` §4.4, documented per the DESIGN.md "Approval"
section ("Deviations require a documented rationale").** DESIGN.md §4.4
requires new tables to carry `created_at`/`updated_at`. This config table is
exempt: it is a single-user key/value store with at most one row per setting
key, holds no records that are listed, synced, or audited over time, and the
upsert in §3.2 overwrites in place — so creation/update timestamps would be
dead columns. The convention exists for the data tables (`contacts`,
`custom_fields`) where row history and Google-etag comparison matter; it does
not apply here.

The migration runner (`init_db` in `db.py`) runs every `*.sql` in sorted order
on each startup with no applied-migrations bookkeeping, so each file must be
safe to re-run. **This new file** uses `CREATE TABLE IF NOT EXISTS`, so once the
table exists each subsequent startup is a no-op. (Tracking *which* migrations
have already run — schema-version bookkeeping — is CL-0008's concern, out of
scope here per §2.)

### 3.2 Module — `settings.py`

A small, focused module (data access only, no Flask request objects):

```python
SETTINGS_DEFAULTS: dict[str, str]      # the canonical defaults from §2 table
SETTINGS_VALIDATORS: dict[str, Callable[[str], bool]]   # per-key validation

def get_settings(db: sqlite3.Connection) -> dict[str, str]:
    """Return SETTINGS_DEFAULTS overlaid with stored rows."""

def update_settings(db: sqlite3.Connection, updates: dict[str, str]) -> list[str]:
    """Validate and upsert. Returns a list of human-readable errors; on any
    error nothing is written (all-or-nothing)."""
```

- `get_settings` reads all rows once, overlays onto a copy of the defaults.
  Unknown stored keys (e.g. a setting removed in a later version) are ignored
  on read, so an old row never poisons template context.
- Validator contracts, one per key:
  - `timezone` → membership in `zoneinfo.available_timezones()`.
  - `phone_region` → membership in `phonenumbers.SUPPORTED_REGIONS`
    (`from phonenumbers import SUPPORTED_REGIONS`).
  - `date_format` → `value in DATE_FORMATS` (the five keys `dmy_hm`, `mdy_hm`,
    `iso`, `dmy`, `mdy` from §5).
  - `theme`, `density`, `view`, `sort`, `sort_dir`, `default_type` → membership
    in their literal allowed-value sets from the §2 table.
  - `per_page` → integer-parseable and clamped (see below).
  (All listed library symbols verified present in the installed deps.)
- `update_settings` validates every incoming value against
  `SETTINGS_VALIDATORS`; `per_page` is parsed and clamped to
  `1`–`config.MAX_CONTACTS_PER_PAGE` (currently 200) — the constant, never a
  second hardcoded literal, so the cap can't drift from `config.py`. Invalid
  input returns errors and writes nothing — the page re-renders with the
  errors, mirroring the existing contact-form validation pattern.
- Upsert via `INSERT ... ON CONFLICT(key) DO UPDATE SET value=excluded.value`.
- Parameterised queries only (DESIGN.md SQL standard).

### 3.3 Defense-in-depth note

Validation is centralised in `settings.py`, so the `friendly_date` filter and
the contacts route can trust the stored values. Where a stored value is still
fed to an external library (timezone → `zoneinfo`, region → `phonenumbers`),
the consumer keeps its existing try/except fallback, so a value that somehow
becomes invalid degrades gracefully rather than 500-ing.

## 4. Applying settings per request

1. **Load once per request.** A `before_request` hook in `create_app` loads
   `get_settings(get_db())` into `flask.g.settings`. One indexed primary-key
   scan of a tiny table — negligible for a localhost single-user app.
   **Registration order matters:** register this loader *before* `_check_csrf`.
   Flask runs `before_request` hooks in registration order and stops at the
   first one that returns/aborts — so on a CSRF-rejected POST, `_check_csrf`
   `abort(403)` ends the chain. If the loader is registered first it has
   already run and set `g.settings`; the error page can then render normally.
   (The error page renders the `base.html` templates, which read `settings` via
   the context processor in item 2 — that read happens at render time, after
   `before_request`, so it needs `g.settings` to already exist.)
2. **Expose to templates.** Extend the existing `_inject_globals` **context
   processor** (app.py:58-70 — runs at template-render time, not as a
   `before_request`; today it returns `csrf_token`, `active_nav`,
   `contact_count`) to *also* return `settings`. It keeps its current returns
   and its own `contact_count` DB read unchanged — the new `before_request`
   loader (item 1) does not absorb that read; the two are independent. For the
   settings value use `getattr(g, 'settings', None) or SETTINGS_DEFAULTS` as
   belt-and-braces for the one path no `before_request` covers — a 500 fired
   before any hook runs (e.g. a DB-open failure) — so an error page never
   raises a second exception over a missing `g.settings`.
3. **`friendly_date`** reads `g.settings['timezone']` and
   `g.settings['date_format']`:
   - Parse the stored ISO-8601 UTC string (unchanged).
   - Convert to the chosen zone via `zoneinfo.ZoneInfo(tz)` (UTC stays UTC).
   - Look up the strftime pattern with
     `DATE_FORMATS.get(key, DATE_FORMATS['dmy_hm'])` (`'dmy_hm'` is the default
     key from §2/§5) — an unknown key falls back to the default pattern, it
     does **not** raise (so there is no `KeyError` path from the catalogue).
   - Keep the existing `try/except (ValueError, AttributeError)` → return raw,
     and extend the except tuple with `ZoneInfoNotFoundError`
     (`from zoneinfo import ZoneInfoNotFoundError`). Note it subclasses
     `KeyError`, **not** `ValueError`, so it is *not* already covered by the
     existing tuple and must be added explicitly — otherwise a bad stored
     timezone raises and breaks rendering.
4. **Theme / layout** are server-rendered (see §6) — no JS round trip, no flash.

`g.settings` is request-scoped, so a save takes effect on the very next page
load with no restart.

## 5. Date format catalogue

A curated map in `settings.py` (no free-text strftime from the user — avoids
garbage/locale surprises and keeps the choice list finite and validated):

```python
DATE_FORMATS = {
    'dmy_hm':  '%d %b %Y, %H:%M',   # 30 Jun 2026, 14:30  (current default)
    'mdy_hm':  '%b %d %Y, %I:%M %p',# Jun 30 2026, 02:30 PM
    'iso':     '%Y-%m-%d %H:%M',    # 2026-06-30 14:30
    'dmy':     '%d %b %Y',          # 30 Jun 2026
    'mdy':     '%m/%d/%Y',          # 06/30/2026
}
```

The Settings page shows each option rendered against a live example timestamp
so the user picks by appearance, not by code.

## 6. Theme & layout (server-rendered)

Per the user's decision: one source of truth, applied on render.

- `base.html` line 2 becomes
  `<html lang="en"{% if settings.theme %} data-theme="{{ settings.theme }}"{% endif %}>`
  and `<body class="density-{{ settings.density }} view-{{ settings.view }}">`.
  **Conditional emission matters:** the `auto` default stores `theme == ''`;
  emitting `data-theme=""` would be a present-but-empty attribute that
  `[data-theme="dark"]`-style palette selectors do not match but bare
  `[data-theme]` presence selectors would — so the attribute is omitted
  entirely when auto, preserving today's no-attribute behaviour. This is
  load-bearing: `static/style.css` keys the auto palette on
  `:root:not([data-theme])` (style.css:37) and named palettes on
  `[data-theme="dark"]` etc., so a present-but-empty `data-theme=""` would
  break auto styling. The first server paint already carries the right theme —
  the current "flash of wrong theme" disappears.
- **Removed — three sites, ~85 lines total:**
  1. The pre-paint theme IIFE, `static/app.js:1-9`.
  2. The theme-picker logic block, `static/app.js:15-59` (toggle/dropdown/
     `applyTheme`/`localStorage`).
  3. The `.theme-picker` markup in the nav, `base.html:18-48` (the toggle
     button + 8 `.theme-option` buttons, including their inline `style=`
     swatches — which also matters for CL-0012's `style-src` tightening).

  **Keep-boundary:** `static/app.js:10-14` is the second IIFE's wrapper
  (`(function () { 'use strict';` + comment) and is **retained** — only the
  theme-picker *statements* at 15-59 are excised from inside it. Removing 1-9
  and 15-59 must leave 10-14 and 60+ intact, or the IIFE braces unbalance.
  The rest of `app.js` (flash dismiss, modal, shortcuts, bulk select, recently
  viewed, custom fields) is untouched.
- `static/style.css` gains:
  - `.density-compact` overrides (tighter spacing) layered on the existing
    `[data-theme=...]` palettes.
  - `.view-card` contact-list styling (card grid) as an alternative to the
    current list/table — net-new, behind the body class so `.view-list`
    (default) is the existing look.
- CSP unchanged and still satisfied (no inline script added; the theme is an
  attribute, not script). `style-src 'unsafe-inline'` is **not** relied on by
  this change (tightening it is the separate CL-0012).

## 7. Phone region + shared helper (folds in CL-0016)

- New module `phoneutil.py` with one function:
  ```python
  def format_phone(raw: str, region: str) -> str:
      """Parse to international format; return raw if unparseable."""
  ```
  Body is the current `format_phone` from `routes/contacts.py` with `region`
  as a parameter instead of the module constant.
- `routes/contacts.py`: delete its local `format_phone` + `DEFAULT_REGION`;
  update the call-site inside `_validate_form` (currently `phone =
  format_phone(phone)`, contacts.py:102) to
  `phone = phoneutil.format_phone(phone, g.settings['phone_region'])`.
- `google_sync.py`: delete its `_format_phone` + `DEFAULT_REGION`; call the
  shared helper. `google_sync.py` must stay free of `flask.g`/request coupling,
  so the region is **threaded in as a parameter** through the call chain rather
  than read from `g`. The three signatures change:
  - `sync_contacts(config, db)` → `sync_contacts(config, db, region: str)`
  - `_upsert_person(db, person)` → `_upsert_person(db, person, region: str)`
  - the current `_format_phone(value)` call inside `_upsert_person`
    (google_sync.py:194) becomes
    `phoneutil.format_phone(value, region) if value else value`.
  The shared `phoneutil.format_phone(raw: str, region: str) -> str` takes a
  non-empty `str` (matching the `routes/contacts.py` caller), so the
  None/empty guard that `_format_phone(raw: str | None)` did internally moves
  to this call-site (the `if value else value` above), preserving today's
  "blank phone stays blank" behaviour.
  The sync route (`routes/sync.py`, which runs in request context) reads
  `g.settings['phone_region']` and passes it to `sync_contacts(...)`.

## 8. UI / route

- New blueprint `routes/settings.py` (`bp = Blueprint('settings', __name__)`):
  - `GET /settings` → render `settings.html` with current `g.settings`,
    plus the choice lists (timezones, date-format examples, themes, regions).
  - `POST /settings` → `update_settings`; on success `flash` + redirect to
    `/settings`; on validation error re-render with errors (HTTP 400), same
    shape as the contact form. The error re-render **must pass the same
    choice-list context as `GET`** (timezones, date-format examples, themes,
    regions) plus the submitted values — otherwise the template references
    undefined variables and 500s while reporting a 400.
  - CSRF enforced by the existing global `_check_csrf` before-request hook.
- `base.html` nav gains a "Settings" link (gear icon), `active_nav`-aware like
  the others.
- New template `templates/settings.html` extending `base.html`: one `<form
  method="post">` with grouped `<fieldset>`s (Appearance, Dates & Time,
  Contacts & Phone), native `<select>`/`<input>` controls, a Save button.
  Server-rendered selected states; no JS required (progressive enhancement
  consistent with the rest of the app).

## 9. Consuming the new defaults

**`routes/contacts.py` `contact_list`:** when the request has no explicit
`per_page` / `sort` / `dir` query arg, fall back to the user's settings
instead of the hardcoded `50` / `name` / `asc`.

- **Absence must be detected explicitly** — the current code bakes the default
  into `request.args.get('sort', 'name')`, which cannot tell "absent" from
  "present-but-equal-to-default". Check presence first, e.g.
  `request.args.get('per_page', type=int)` returning `None`, or
  `request.args.get('sort') or g.settings['sort']`, before applying the stored
  default. An explicit query arg (e.g. the user clicking a column header) still
  wins, so sortable headers keep working.
- **Page clamp is already handled** — the route recomputes `total_pages` from
  the effective `per_page` and clamps `page` into range; `models.py`
  `list_contacts` also clamps `per_page`/`page` independently at the data
  layer. So a newly-saved smaller `per_page` can never leave `page` out of
  bounds — no extra handling needed.

**`routes/contacts.py` `new_contact`:** pre-select `g.settings['default_type']`
in the rendered form.

## 10. Testing

New `tests/test_settings.py`:

- **Model:** `get_settings` returns defaults on an empty table; overlays a
  saved row; ignores an unknown stored key. `update_settings` saves valid
  values; rejects each invalid value (bad timezone, bad theme, out-of-range
  per_page, bad region) and writes nothing on rejection. **All-or-nothing:** a
  batch mixing one invalid key with several valid ones writes *none* of them
  (asserts the §3.2 atomicity contract).
- **Route:** `GET /settings` renders 200; `POST /settings` with valid data
  persists and redirects; with invalid data returns 400 and the error;
  `POST` without a CSRF token returns 403.
- **Filter:** `friendly_date` honours timezone (UTC → a +offset zone shifts
  the displayed hour) and the chosen format key; a bad stored value falls
  back to raw without raising.

Existing `tests/test_routes.py` / `tests/test_models.py` must stay green;
where they assert the old hardcoded date string or per-page default they are
updated to the default-settings expectation (defaults are unchanged values,
so most assertions hold as-is).

## 11. Standards compliance (DESIGN.md)

- **SQL:** parameterised only; upsert uses bound params.
- **XSS:** all settings rendered through Jinja autoescaping; `data-theme`/body
  classes come from a validated whitelist, never free text.
- **CSRF:** settings POST goes through the existing token check.
- **Secrets:** settings are preferences, not secrets — DB is the right home;
  nothing new under `~/.config/contact-list/`.
- **Dependencies:** none added. `zoneinfo` is stdlib; `phonenumbers` already
  a dependency.
- **Type hints / PEP 8 / line ≤100 / specific exceptions:** followed.

## 12. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Stored value becomes invalid after a version change | `get_settings` overlays onto defaults; consumers keep try/except fallbacks (§3.3, §4). |
| Timezone list is long (~600 entries) in a `<select>` | Acceptable for a native select; a curated "common" optgroup can be added later if needed (not in scope). |
| Removing browser theme breaks a user mid-session | Theme now server-rendered; first load after deploy shows the DB default (auto) until the user re-picks — acceptable for a single-user local app. |
| Sync path lacks request context | Region passed into `phoneutil.format_phone` from the caller, not read from `g` inside `google_sync.py` (§7). |
```

