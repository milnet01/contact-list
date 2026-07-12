# Contact List App — Design Document

**Version:** 1.0
**Date:** 2026-03-30
**Status:** Draft

---

## 1. Overview

A lightweight, secure contact management application for storing, searching, and syncing contacts. Supports both individual and company contacts, standard contact fields, user-defined custom fields, and bidirectional Google Contacts integration.

---

## 2. Goals & Constraints

| Priority | Goal |
|----------|------|
| 1 | **Security** — Zero tolerance for injection, XSS, CSRF, or credential leakage |
| 2 | **Lightweight** — Minimal memory footprint, minimal dependencies, fast startup |
| 3 | **Efficiency** — Sub-100ms response times for local operations, lazy loading, pagination |
| 4 | **Extensibility** — Custom fields without schema changes; design standards for future iterations |

**Non-goals (v1):** Multi-user auth, cloud deployment, mobile app.

---

## 3. Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | **Python 3.12+** | Pre-installed on most Linux systems, strong Google API support. 3.12+ specifically: the Google-sync per-record SAVEPOINT/ROLLBACK isolation (`google_sync.sync_contacts`) relies on 3.12+ sqlite3 transaction semantics; on legacy (≤3.11) sqlite3 a SAVEPOINT in autocommit can weaken the rollback (CL-0019). |
| Web framework | **Flask 3.x** (with Jinja2) | ~1 MB installed, battle-tested, minimal overhead |
| Database | **SQLite 3** | Zero-server, single-file, ~600 KB memory baseline, ACID-compliant |
| Frontend | **Vanilla HTML + CSS + JS** | No build step, no node_modules, zero JS framework overhead |
| Google sync | **Google People API v1** | Official API; uses `google-api-python-client` + `google-auth-oauthlib` |
| CSS | **Classless/minimal CSS** (e.g. Pico CSS, ~10 KB) | Responsive without a framework |

### Dependency Budget

Total pip dependencies must stay at or under **8 packages** (direct). No C-extension dependencies beyond what ships with Python — **with one authorised exception: Pillow** (for CL-0035 photo thumbnailing; the user lifted the ban specifically for that need). pystray (CL-0052 tray icon) is **pure Python**, so it adds no C-extension pip dependency; its Linux appindicator backend relies on a GI/GTK3 stack that is a build-time bundling artifact carried in the AppImage (§15), not a declared dependency, so the "one authorised exception: Pillow" wording stands. Every new dependency requires justification in a PR description.

```
# Runtime
flask>=3.1.1,<4.0
google-api-python-client>=2.0,<3.0
google-auth>=2.0,<3.0
google-auth-oauthlib>=1.0,<2.0
google-auth-httplib2>=0.2,<1.0
phonenumbers>=9.0,<10.0
pillow>=12.0,<13.0
pystray>=0.19,<0.20
# Test-only (not counted against the runtime footprint)
pytest>=9.0,<10.0
```

Eight runtime packages (at the 8-direct budget); pystray provides the CL-0052 system-tray icon — core desktop UX, justified like the Pillow exception (its Linux backend = Ayatana AppIndicator via gi/GTK3 bundled into the AppImage; macOS = pyobjc-framework-Quartz; Windows = nothing extra; python-xlib ships transitively but the xorg backend is never selected). `google-auth` is listed
explicitly because the sync code imports it directly (`google.oauth2` /
`google.auth`) rather than relying on it transitively. `pytest` is a test-only
dependency and does not affect the running app.

PyInstaller, appimagetool, and the OS icon tools (CL-0049, §15) are build-time
only, not runtime deps; the 8-runtime budget is unaffected.

### Dependency Versioning Policy

**Default: latest.** Every dependency tracks its latest stable release — for
features **and** security. Scope: runtime pip packages (`requirements.txt`), dev
/ CI tools (`ruff`, `mypy`, `pytest`), GitHub Actions (`actions/checkout`,
`actions/setup-python`) and the CI runner image, and the Python runtime itself.
The `requirements.txt` constraints cap only the **major** version, so an
unreviewed breaking major cannot land silently; within that cap the newest
release is always installed, and the cap is raised promptly once a new major is
vetted.

**Holding a version back is the rare exception — allowed only when a newer
version explicitly breaks a feature and there is no reasonable workaround.** Every
such exception MUST be recorded in the register below with (a) the exact version
that first broke the feature and (b) a re-test trigger, so that when a release
newer than the broken one ships we re-test and move forward rather than staying
pinned indefinitely. An undocumented downgrade or below-latest pin is a policy
violation.

Check at the start of a release cycle, or whenever touching a manifest/workflow:

```bash
./venv/bin/pip list --outdated                              # pip packages
gh api repos/actions/checkout/releases/latest -q .tag_name   # a GitHub Action
```

During that sweep, also revisit every row in the register below: if a release
**newer than its "First broken at" version** now exists, re-test the feature
against it. If it passes, delete the row and move to latest; if it still breaks,
update "Latest available" / "Re-test when" so the row stays accurate. A held-back
pin is never permanent — it lives only until a fixed upstream release lands.

### Dependency Exceptions & Breakage Register

One row per dependency held below its latest release. Empty is the healthy state.

| Dependency | Pinned to | Latest available | First broken at | Symptom / what breaks | Re-test when | Noted |
|------------|-----------|------------------|-----------------|-----------------------|--------------|-------|
| _None_ | — | — | — | All dependencies track their latest release. Audited 2026-07-04: flask 3.1.3, google-api-python-client 2.198.0, google-auth 2.55.1, google-auth-oauthlib 1.4.0, google-auth-httplib2 0.4.0, phonenumbers 9.0.34, pillow 12.3.0, pytest 9.1.1, ruff 0.15.20, mypy 2.1.0; actions/checkout@v7 (v7.0.0), actions/setup-python@v6 (v6.3.0). | — | 2026-07-04 |

---

## 4. Data Model

SQLite database: `contacts.db`

### 4.1 `contacts` Table

```sql
CREATE TABLE contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT    NOT NULL CHECK(type IN ('individual', 'company')),
    name        TEXT    NOT NULL,
    email       TEXT,
    phone       TEXT,
    notes       TEXT,
    google_id   TEXT    UNIQUE,          -- resourceName from People API, NULL if local-only
    etag        TEXT,                     -- Google sync etag for conflict detection
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_contacts_type ON contacts(type);
CREATE INDEX idx_contacts_name ON contacts(name COLLATE NOCASE);
CREATE INDEX idx_contacts_google_id ON contacts(google_id);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_phone ON contacts(phone);
```

### 4.2 `custom_fields` Table (EAV Pattern)

```sql
CREATE TABLE custom_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    field_name  TEXT    NOT NULL,
    field_value TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_cf_contact ON custom_fields(contact_id);
CREATE INDEX idx_cf_name    ON custom_fields(field_name COLLATE NOCASE);
CREATE UNIQUE INDEX idx_cf_unique ON custom_fields(contact_id, field_name COLLATE NOCASE);
```

### 4.3 `sync_state` Table

```sql
CREATE TABLE sync_state (
    id              INTEGER PRIMARY KEY CHECK(id = 1),  -- singleton row
    sync_token      TEXT,                                -- Google incremental sync token
    last_synced_at  TEXT
);
```

### 4.4 `contact_edits` Table (CL-0033)

```sql
CREATE TABLE contact_edits (
    contact_id INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    edited_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

A companion table (like `contact_photos`) recording the last **user** edit of a
contact, written only by the model writers — never by the Google-sync pull — so it
stays an honest "last edited by you" signal, immune to a sync refreshing the row.
No row exists until the user genuinely edits a contact (no backfill). Powers the
two-way-sync dirty detection and the "Last edited"/list/footer display.

### 4.5 Tags (`tags` + `contact_tags`, CL-0037)

```sql
CREATE TABLE tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE contact_tags (
    contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id)     ON DELETE CASCADE,
    PRIMARY KEY (contact_id, tag_id)
);
CREATE INDEX idx_contact_tags_tag ON contact_tags(tag_id);
```

A many-to-many label store. `tags.name` is case-insensitively unique (NOCASE), so
"Family"/"family" collapse to one row (stored casing = first typed). A tag is
created on first use and garbage-collected when its last contact drops it, so the
in-use set is always exactly what `get_all_tags` (an INNER JOIN) surfaces. The list
filter is an AND of scalar `id IN (subquery)` membership tests (one per selected
tag) — no JOIN, so no row fan-out. Being a pure join table, `contact_tags` carries
no timestamps (see §4.6). *Deliberately out of scope for CL-0037:* CSV
export/import of tags, Google-group sync, and per-tag colours (future items).

### 4.6 Schema Conventions (for future iterations)

- All timestamps are ISO 8601 UTC strings.
- All text columns use UTF-8.
- Foreign keys always use `ON DELETE CASCADE`.
- New tables should include `created_at` and `updated_at` — **except** a table
  whose sole purpose is a single domain timestamp, which may name that column
  instead (e.g. `contact_edits.edited_at`, `contact_photos.updated_at`), or a pure
  join table (`contact_tags`), which needs none. (This convention is aspirational:
  only `contacts` currently carries both; the companion tables deliberately do not.)
- Migrations are sequential numbered SQL files in `migrations/`.

---

## 5. Architecture

```
Contact_List/
├── DESIGN.md              # This document
├── requirements.txt       # Pinned dependencies
├── app.py                 # Entry point — Flask app factory
├── config.py              # Configuration (env-based)
├── db.py                  # SQLite connection management
├── models.py              # Data access layer (plain functions, no ORM)
├── google_sync.py         # Google People API integration
├── routes/
│   ├── contacts.py        # CRUD routes
│   └── sync.py            # Google sync routes
├── templates/
│   ├── base.html          # Layout shell
│   ├── contacts.html      # Contact list view
│   ├── contact_detail.html
│   └── contact_form.html
├── static/
│   ├── style.css
│   └── app.js             # Minimal JS for search/filter/custom fields
├── migrations/
│   ├── 001_initial.sql
│   └── 002_add_indexes.sql
└── tests/
    ├── test_models.py
    └── test_routes.py
```

### 5.1 Design Principles

1. **No ORM.** Direct parameterized SQL via `sqlite3`. Avoids abstraction overhead and hidden queries.
2. **App factory pattern.** `create_app()` returns a configured Flask app — testable, no global state.
3. **Server-side rendering.** Jinja2 templates. JS is progressive enhancement only (search filtering, dynamic custom field rows).
4. **Stateless requests.** No server-side sessions beyond Flask's signed cookie (for CSRF token).

---

## 6. Security Standards

These are **mandatory** for all current and future code.

### 6.1 Input Handling

| Rule | Implementation |
|------|---------------|
| SQL injection prevention | **Parameterized queries only.** Never use f-strings or `.format()` in SQL. |
| XSS prevention | Jinja2 autoescaping enabled globally (`autoescape=True`, Flask default). Manual `| e` filter on any `Markup()` usage. |
| CSRF protection | Signed token in every state-changing form. Validate on POST/PUT/DELETE. |
| Input validation | Whitelist validation: `type` must be `individual` or `company`. `field_name` must match `^[a-zA-Z0-9_ ]{1,64}$`. Phone/email validated with regex, not sanitized. |
| File uploads | CSV/vCard import (v1.1) and contact photos (v1.2, CL-0026). Photos are validated by magic bytes (JPEG/PNG/GIF/WebP allow-list; SVG rejected) and a 4 MiB cap, stored on disk under `PHOTOS_DIR` (never blobs in the DB), and served same-origin with `nosniff` — see `photos.py`. CL-0035 additionally decodes/re-encodes each photo via Pillow to make a 256 px thumbnail, but only **behind** that magic-byte allow-list + size cap (the allow-list stays the gatekeeper; a decode failure is non-fatal and falls back to the original) — see `docs/specs/2026-07-04-photo-thumbnails-design.md` §6. |

### 6.2 Google OAuth

| Rule | Implementation |
|------|---------------|
| Token storage | Tokens stored in `~/.config/contact-list/token.json` with `0600` permissions. Never in the database or repo. |
| Scopes | Request `https://www.googleapis.com/auth/contacts` (read-write) — the minimum for two-way sync (CL-0033). `SCOPES` is defined once in `google_sync.py` and imported by `google_auth.py` so they cannot diverge. A legacy read-only token is rejected and prompts a reconnect. |
| Client secret | Stored in `~/.config/contact-list/credentials.json`, never committed. `.gitignore` enforced. |
| Token refresh | Use `google-auth` automatic refresh. Revoke and re-auth on persistent `RefreshError`. |

### 6.3 General

- **No `eval()`, `exec()`, or `pickle` on user data.** Ever.
- **No shell commands** from user input.
- **Dependency pinning.** All versions pinned in `requirements.txt`. Audit with `pip-audit` before releases.
- **Error pages** must not leak stack traces, file paths, or SQL. Use Flask `errorhandler` decorators.
- **HTTPS only** if ever deployed beyond localhost. v1 runs on `127.0.0.1` only.
- **Content-Security-Policy** header: `default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'`. Inline `style=` attributes were moved into the stylesheet so `style-src` no longer needs `'unsafe-inline'` (CL-0012).
- **Local process control** (`POST /settings/server`, CL-0046). The Settings page can restart or shut down the server (the app is launched from a desktop icon with no terminal). This process-control power is safe because it is reachable only on `127.0.0.1`, is CSRF-gated like every other POST, and is scoped to a `restart`/`shutdown` allow-list — nothing user-supplied ever reaches the `subprocess.Popen` argv, which is built only from `sys.executable` + `sys.argv` and passed as a list (no `shell=True`, no argument injection).

---

## 7. Efficiency & Memory Standards

### 7.1 Runtime Targets

| Metric | Target |
|--------|--------|
| Cold start | < 500 ms |
| Memory at idle | < 30 MB RSS |
| Memory at 10k contacts | < 50 MB RSS |
| List page load (100 contacts) | < 100 ms |
| Search (10k contacts) | < 200 ms |
| Google sync (1000 contacts) | < 10 s |

The `< 500 ms` cold-start target is a **source-mode** figure (`python app.py`);
the frozen launchers' (CL-0049, §15) first-launch unpack — notably the Windows
onefile every-launch extraction, ~1–2 s — is exempt.

### 7.2 Implementation Rules

- **Pagination.** All list endpoints paginate (default 50, max 200 per page).
- **No eager loading of custom fields on list view.** Load custom fields only on detail/edit views.
- **Single SQLite connection per request.** Opened on first query, closed on teardown. No connection pooling needed for SQLite.
- **Streaming responses** for any future CSV/vCard export (use generators, not full in-memory buffers).
- **Google sync is batched.** Use `people.connections.list` with `pageSize=1000` and `syncToken` for incremental sync. Never fetch all contacts on every sync.
- **No background threads or task queues** for application work in v1. Sync is user-triggered. *Exception (CL-0046):* a single short-lived daemon thread may defer a server restart/shutdown until the HTTP response has flushed — it does no application work and the process respawns a fresh child then exits milliseconds later. See `docs/specs/2026-07-05-server-restart-control.md`. This carve-out extends to the launcher's (CL-0049, §15) one-shot browser-open daemon thread — it opens the browser once after the socket is up, then does no further application work. *Exception (CL-0052):* the system-tray icon owns the main thread, so the HTTP server runs on **one dedicated long-lived background thread** for the whole app lifetime — a materially stronger carve-out than the one-shot threads above (serving HTTP *is* application work). No shared mutable app state crosses threads beyond the server socket; Quit calls `server.shutdown()` then `join()`s the thread. See `docs/specs/2026-07-12-system-tray-icon.md` §5.
- **Indexes** on all columns used in WHERE/ORDER BY (see schema above).

### 7.3 What to Avoid

- ORMs (SQLAlchemy adds ~15 MB RSS overhead).
- JS frameworks (React/Vue/Svelte add build complexity and bundle size).
- Image/avatar storage as **DB blobs** — still avoided. Contact photos (v1.2,
  CL-0026) are stored as **files** under `PHOTOS_DIR` with only the extension in
  the DB, and served locally (not hot-linked) to keep the CSP strict and work
  offline.
- WebSocket connections (unnecessary for this use case).
- Caching layers (SQLite is fast enough for local single-user).

---

## 8. Google Contacts Integration

### 8.1 Setup Flow

1. User creates a Google Cloud project and enables the People API.
2. User downloads OAuth 2.0 client credentials JSON.
3. User places it at `~/.config/contact-list/credentials.json`.
4. On first sync, app opens browser for OAuth consent.
5. Token is saved to `~/.config/contact-list/token.json` (mode `0600`).

### 8.2 Sync Strategy

- **Sync direction (v2.0):** bidirectional — pull all changed Google contacts, then
  push local-only contacts (create) and locally-edited linked contacts (update).
  Deletions are **not** pushed (CL-0033).
- **Conflict resolution:** automatic last-write-wins by Google `updateTime` vs the
  local `edited_at` (newest edit wins; tie → Google), with a fresh-etag write-time
  backstop. Local-only contacts **are** pushed as new Google contacts.
- **Matching:** Contacts matched by `google_id` (People API `resourceName`).
- **Incremental:** Use `syncToken` from People API. First sync is full, subsequent syncs are delta.
- **Field mapping:**

| Google Field | Local Field |
|-------------|-------------|
| `names[0].displayName` | `name` |
| `emailAddresses[0].value` | `email` |
| `phoneNumbers[0].value` | `phone` |
| `organizations[0].name` | `type='company'` or custom field |
| `biographies[0].value` | `notes` |
| `birthdays[0].date` | custom field: `birthday` |
| `addresses[0].formattedValue` | custom field: `address` |

### 8.3 Bidirectional Sync (v2.0 — CL-0033, shipped)

- Requires the `contacts` (read-write) scope, not `contacts.readonly`. A legacy
  read-only token is detected (via the token file's own scopes) and prompts a
  reconnect. `SCOPES` is a single literal in `google_sync.py`, imported by
  `google_auth.py`.
- Tracks a dedicated `edited_at` (`contact_edits`, §4.4) and compares Google
  `updateTime` timestamps; the `etag` is the write-time precondition backstop, not
  the conflict signal.
- Automatic last-write-wins by timestamp (no per-conflict prompt), with a post-sync
  report. Multi-valued Google fields (email/phone) are read-modify-written to
  preserve secondary entries. Spec: `docs/specs/2026-07-02-two-way-google-sync.md`.

---

## 9. API / Route Design

All routes are server-rendered HTML. No REST/JSON API in v1 (add in v2 if needed).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirect to `/contacts` |
| GET | `/contacts` | Paginated contact list with search/filter/sort |
| GET | `/contacts/new` | New contact form |
| POST | `/contacts` | Create contact (with duplicate detection) |
| GET | `/contacts/<id>` | Contact detail view |
| GET | `/contacts/<id>/edit` | Edit contact form |
| POST | `/contacts/<id>` | Update contact |
| POST | `/contacts/<id>/delete` | Delete contact |
| POST | `/contacts/<id>/favourite` | Toggle favourite / pinned status (CL-0039) |
| GET | `/contacts/<id>/photo` | Stream the contact's stored photo (CL-0026) |
| GET | `/contacts/export` | CSV export of all contacts |
| GET | `/contacts/duplicates` | Scan and display duplicate contacts |
| GET | `/sync` | Google sync status page |
| POST | `/sync/start` | Trigger Google sync (import and export) |
| POST | `/sync/authorize` | Start OAuth flow (Desktop client) |
| POST | `/sync/disconnect` | Revoke Google credentials |
| GET | `/settings` | Settings page |
| POST | `/settings` | Save settings |
| POST | `/settings/server` | Restart or shut down the local server (CL-0046) |

### 9.1 Query Parameters for `/contacts`

| Param | Description |
|-------|-------------|
| `q` | Search term (matches name, email, phone, notes, and custom-field values) |
| `type` | Filter by `individual` or `company` |
| `letter` | Filter by first letter (A-Z or `#` for non-alpha) |
| `tag` | Filter by tag (repeatable; matches contacts carrying **all** given tags) |
| `page` | Page number (clamped to valid range) |
| `per_page` | Items per page (1-200, default 50) |
| `sort` | Sort column: `name`, `type`, `created`, `updated` |
| `dir` | Sort direction: `asc` or `desc` |

---

## 10. UI Design Principles

- **Mobile-first responsive layout.** Works on phone and desktop.
- **No JavaScript required for core functionality.** JS enhances (live search, dynamic custom field rows, drag-and-drop reorder) but forms work without it.
- **Accessible.** Semantic HTML, ARIA labels, `focus-visible` outlines, `prefers-reduced-motion` support, sufficient contrast, keyboard navigable.
- **Print-friendly.** `@media print` rules hide navigation and action buttons.
- **Minimal color palette.** Neutral base, single accent color for actions.
- **Fast perceived performance.** Full page loads, no SPA loading spinners.

### 10.1 Page Construction Standard (CL-0047)

Every page is built to one standard so the app reads as one product. Full spec:
`docs/specs/2026-07-05-page-construction-standard.md`. In brief:

- **Shell:** every page `extends base.html`.
- **Header:** one `<h1>` per page via the `page_header` macro (`_macros.html`) —
  title + optional right-aligned actions; `contact_detail` keeps its richer
  `.detail-header` variant.
- **Sections:** the `.card` look is canonical. A `<fieldset>` in a form renders
  identically to a `<div class="card">` (shared surface/border/radius/shadow, and
  the `<legend>` / `.card-title` full-width underlined header).
- **Forms:** each field is a `.form-group` (label above control); actions in a
  `.form-actions` row.
- **Tabs:** multi-section pages (Settings) use `.tabs` — progressive enhancement,
  tab bar hidden until `app.js` adds `.js-tabs`; JS-off shows all panels. Tab
  buttons are `type="button"`; confirms use `data-confirm` (no inline JS, CSP).

---

## 11. Testing Standards

- **Unit tests** for all `models.py` functions (use `tmp_path` file-based SQLite).
- **Route tests** using Flask test client.
- **No mocking of SQLite.** Tests use real in-memory databases.
- **Google sync tests** mock the Google API client (external boundary).
- **Run with:** `python -m pytest tests/ -v`

---

## 12. Coding Standards (for all future iterations)

1. **Type hints** on all function signatures.
2. **Docstrings** only where behavior is non-obvious.
3. **No classes** unless encapsulating mutable state. Prefer plain functions.
4. **No global mutable state.** Use Flask `g` or app context.
5. **Imports** grouped: stdlib, third-party, local — separated by blank lines.
6. **Line length:** 100 chars max.
7. **Formatting:** Follow PEP 8. Use `ruff` for linting if available.
8. **Error handling:** Catch specific exceptions. Never bare `except:`.
9. **Logging:** Use Python `logging` module, not `print()`.
10. **Commits:** Each commit must leave the app in a working state.

---

## 13. Versioning & Iteration Plan

| Version | Scope |
|---------|-------|
| **v1.0** | Local CRUD, custom fields, Google import, search, pagination |
| v1.1 | CSV import, vCard import/export, merge duplicates |
| v1.2 | Contact photos/avatars (Google-synced + manual upload, CL-0026) |
| v2.0 | Bidirectional Google sync (CL-0033) + honest last-edited timestamp |
| v2.1 | Contact groups/tags |
| v2.2 | REST JSON API |
| v3.0 | CardDAV server (sync with phone contacts apps) |

---

## 14. File Size Budget

| Component | Max Size |
|-----------|----------|
| Python source — shipped app `.py` (excludes `tests/`) | < 100 KB total (soft) |
| CSS | < 15 KB |
| JavaScript | < 10 KB |
| HTML templates (all) | < 30 KB total |
| SQLite DB (empty) | < 20 KB |
| Total pip install | < 20 MB |

The Python-source figure is a **soft target** — guidance, not a hard gate — and
counts shipped application modules only, not `tests/`. It was raised from the
original < 50 KB when import/export/merge (CL-0022/0023/0024) landed (shipped
app source is ~85 KB after those features); see
`docs/specs/2026-07-01-import-export-merge-design.md` §7.

---

## 15. Packaging & Distribution (CL-0049)

Standalone one-file launchers (`launcher.py`, PyInstaller) let a user run the app
without installing Python. Spec: `docs/specs/2026-07-10-standalone-launchers-design.md`.

**Frozen vs. source resource model.** `launcher.py` is the frozen entrypoint;
`app.py`'s `if __name__ == '__main__'` block is unchanged for `python app.py`.
Read-only resources (`templates/`, `static/`, `migrations/`) are resolved via a
`resource_path()` helper that points at the PyInstaller extraction dir
(`sys._MEIPASS`) when frozen and at the repo root from source — behaviour from
source is byte-identical to today.

**State location.** When frozen, **all** mutable state — the SQLite database,
`photos/`, `token.json`, `credentials.json`, `secret_key`, and the new
`contact-list.log` — lives under the existing private config dir,
`~/.config/contact-list/`, never inside the ephemeral extraction directory. From
source the database path is unchanged (next to the code).

**Per-OS formats.**

| OS | File | Mode |
|----|------|------|
| Linux | `Contact-List-x86_64.AppImage` | onedir (no per-launch unpack) |
| Windows | `Contact-List.exe` | onefile (self-extracts each launch, ~1–2 s) |
| macOS (Apple Silicon) | `Contact-List.dmg` | onedir `.app` bundle |

**Signing posture — unsigned/ad-hoc, not notarized.** No paid code-signing or
notarization is in scope. macOS ships **ad-hoc**-signed (required for Apple
Silicon to execute the binary at all) and Gatekeeper still warns on first open —
the user right-clicks → Open once. Windows ships fully unsigned and SmartScreen
warns — the user clicks More info → Run anyway once. Both are documented in the
README download section, not engineered away.

**Config-dir lock is POSIX-only.** The `0700` permission on `~/.config/contact-list`
(`ensure_private_dir`) is enforced on Linux and macOS. On **Windows**,
`os.chmod` cannot set POSIX mode bits, so this lock is effectively a no-op there;
per-user isolation instead rests on the OS's own user-profile ACLs (each user's
home directory is already private to them by default). `ensure_private_dir`
tolerates a filesystem that ignores POSIX modes (`except OSError`).

---

## Approval

This document must be reviewed and approved before implementation begins. All future iterations must comply with the security, efficiency, and coding standards defined above. Deviations require a documented rationale.
