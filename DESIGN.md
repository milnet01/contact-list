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
| Language | **Python 3.10+** | Pre-installed on most Linux systems, strong Google API support |
| Web framework | **Flask 3.x** (with Jinja2) | ~1 MB installed, battle-tested, minimal overhead |
| Database | **SQLite 3** | Zero-server, single-file, ~600 KB memory baseline, ACID-compliant |
| Frontend | **Vanilla HTML + CSS + JS** | No build step, no node_modules, zero JS framework overhead |
| Google sync | **Google People API v1** | Official API; uses `google-api-python-client` + `google-auth-oauthlib` |
| CSS | **Classless/minimal CSS** (e.g. Pico CSS, ~10 KB) | Responsive without a framework |

### Dependency Budget

Total pip dependencies must stay under **8 packages** (direct). No C-extension dependencies beyond what ships with Python. Every new dependency requires justification in a PR description.

```
flask>=3.1.1,<4.0
google-api-python-client>=2.0,<3.0
google-auth-oauthlib>=1.0,<2.0
google-auth-httplib2>=0.2,<1.0
phonenumbers>=8.13,<9.0
```

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

### 4.4 Schema Conventions (for future iterations)

- All timestamps are ISO 8601 UTC strings.
- All text columns use UTF-8.
- Foreign keys always use `ON DELETE CASCADE`.
- New tables must include `created_at` and `updated_at`.
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
| File uploads | **None allowed** in v1. |

### 6.2 Google OAuth

| Rule | Implementation |
|------|---------------|
| Token storage | Tokens stored in `~/.config/contact-list/token.json` with `0600` permissions. Never in the database or repo. |
| Scopes | Request only `https://www.googleapis.com/auth/contacts.readonly` for import. Upgrade to `.contacts` only if write-sync is added. |
| Client secret | Stored in `~/.config/contact-list/credentials.json`, never committed. `.gitignore` enforced. |
| Token refresh | Use `google-auth` automatic refresh. Revoke and re-auth on persistent `RefreshError`. |

### 6.3 General

- **No `eval()`, `exec()`, or `pickle` on user data.** Ever.
- **No shell commands** from user input.
- **Dependency pinning.** All versions pinned in `requirements.txt`. Audit with `pip-audit` before releases.
- **Error pages** must not leak stack traces, file paths, or SQL. Use Flask `errorhandler` decorators.
- **HTTPS only** if ever deployed beyond localhost. v1 runs on `127.0.0.1` only.
- **Content-Security-Policy** header: `default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'`.

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

### 7.2 Implementation Rules

- **Pagination.** All list endpoints paginate (default 50, max 200 per page).
- **No eager loading of custom fields on list view.** Load custom fields only on detail/edit views.
- **Single SQLite connection per request.** Opened on first query, closed on teardown. No connection pooling needed for SQLite.
- **Streaming responses** for any future CSV/vCard export (use generators, not full in-memory buffers).
- **Google sync is batched.** Use `people.connections.list` with `pageSize=1000` and `syncToken` for incremental sync. Never fetch all contacts on every sync.
- **No background threads or task queues** in v1. Sync is user-triggered.
- **Indexes** on all columns used in WHERE/ORDER BY (see schema above).

### 7.3 What to Avoid

- ORMs (SQLAlchemy adds ~15 MB RSS overhead).
- JS frameworks (React/Vue/Svelte add build complexity and bundle size).
- Image/avatar storage (link to URLs if needed, don't store blobs).
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

- **Import direction (v1):** Google -> Local only.
- **Conflict resolution:** Google is source of truth for imported contacts. Local-only contacts are never pushed.
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

### 8.3 Future: Bidirectional Sync (v2+)

- Requires `contacts` scope (not `contacts.readonly`).
- Track `updated_at` locally and compare with Google `etag`.
- Last-write-wins with user confirmation on conflicts.

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
| GET | `/contacts/export` | CSV export of all contacts |
| GET | `/contacts/duplicates` | Scan and display duplicate contacts |
| GET | `/sync` | Google sync status page |
| POST | `/sync/start` | Trigger Google import |
| POST | `/sync/authorize` | Start OAuth flow (Desktop client) |
| POST | `/sync/disconnect` | Revoke Google credentials |

### 9.1 Query Parameters for `/contacts`

| Param | Description |
|-------|-------------|
| `q` | Search term (matches name, email, phone) |
| `type` | Filter by `individual` or `company` |
| `letter` | Filter by first letter (A-Z or `#` for non-alpha) |
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
| v1.1 | vCard import/export |
| v2.0 | Bidirectional Google sync, REST JSON API |
| v2.1 | Contact groups/tags |
| v3.0 | CardDAV server (sync with phone contacts apps) |

---

## 14. File Size Budget

| Component | Max Size |
|-----------|----------|
| Python source (all `.py`) | < 50 KB total |
| CSS | < 15 KB |
| JavaScript | < 10 KB |
| HTML templates (all) | < 30 KB total |
| SQLite DB (empty) | < 20 KB |
| Total pip install | < 20 MB |

---

## Approval

This document must be reviewed and approved before implementation begins. All future iterations must comply with the security, efficiency, and coding standards defined above. Deviations require a documented rationale.
