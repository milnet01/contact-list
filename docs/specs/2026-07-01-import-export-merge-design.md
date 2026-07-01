# Import / Export / Merge — Design (CL-0022, CL-0023, CL-0024)

Status: Draft (in cold-eyes review)
Date: 2026-07-01
Extends DESIGN.md §9 (routes), §13 (version plan), §14 (file budget). The
DESIGN.md §13 (v1.1 row) and §14 (budget) edits land in the same change-set as
this spec — they are applied, not merely planned. All three features ship in
**v1.1**.

Sections: [1 Overview](#1-overview) · [2 CSV import](#2-csv-import-cl-0022) ·
[3 vCard](#3-vcard-import--export-cl-0023) · [4 Merge](#4-merge-duplicates-cl-0024) ·
[5 Data model](#5-data-model-changes) · [6 Security](#6-security--robustness) ·
[7 Files & budget](#7-new--changed-files--size-budget) · [8 Testing](#8-testing) ·
[9 Invariants](#9-invariants) · [10 Out of scope](#10-out-of-scope).

## 1. Overview

Three related features for getting contacts in and out of the app, plus a
cleanup tool:

- **CL-0022 — CSV import** with a column-mapping screen that learns from prior
  imports.
- **CL-0023 — vCard (.vcf) import and export**, hand-rolled (no new dependency).
- **CL-0024 — Merge** on the Duplicates page: field-level, no data loss.

All three run single-user on localhost, reuse the existing data-access layer
(`models.py`), the `custom_fields` EAV table, and `phoneutil`. No REST/JSON API
is added.

**Shared multi-value rule** (used by §2.3 and §3.2): the first value is the
primary email/phone; every additional value becomes a custom field whose label
is sanitised to pass `valid_field_name` (§2.3). One helper implements it so CSV
and vCard agree.

### 1.1 Routes (all on the existing `contacts` blueprint)

| Method(s) | Path | Endpoint | Purpose |
|-----------|------|----------|---------|
| GET, POST | `/contacts/import` | `contacts.import_view` | GET: upload form. POST: CSV → render mapping screen; vCard → import immediately + summary (§3.2) |
| POST | `/contacts/import/apply` | `contacts.import_apply` | Apply a mapped CSV import + summary |
| GET | `/contacts/export/vcard` | `contacts.export_vcard` | Download all contacts as `.vcf` |
| POST | `/contacts/merge` | `contacts.merge_preview` | Render the read-only field-picker (no writes) |
| POST | `/contacts/merge/apply` | `contacts.merge_apply` | Perform the merge |

Every `url_for(...)` in this spec (e.g. `url_for('contacts.merge_preview')`)
refers to these endpoint names. DESIGN.md §9's route table gains these rows.

## 2. CSV import (CL-0022)

### 2.1 Flow — two stateless screens

1. **Upload** (`GET /contacts/import` form → `POST /contacts/import`
   = `import_view`): user selects a `.csv` (or `.vcf`, §3.2). The file is
   decoded as **`utf-8-sig`** (strips a UTF-8 BOM, which most spreadsheet
   exports carry); a `UnicodeDecodeError` flashes "Could not read file — please
   save it as UTF-8 CSV." and returns to the upload form. Server parses the
   header row and first 5 data rows for a preview. Nothing is written to disk.
2. **Map** (rendered by `import_view` on a CSV POST): one
   `<select name="map_<i>">` per source column `i`, targeting one of
   `Name | Type | Email | Phone | Notes | Custom field | Ignore`; plus a
   `default_type` select (`individual`/`company`, defaulting to the user's
   `default_type` setting) applied to rows whose mapped Type cell is blank or
   absent. The decoded CSV text is carried forward in a hidden
   `<textarea name="csv_text">` (textarea escaping touches only `<` and `&`, so
   inflation is negligible).
3. **Apply** (`POST /contacts/import/apply` = `import_apply`): receives
   `csv_text`, every `map_<i>` select, and `default_type`. It re-parses
   `csv_text` with `csv.reader` (default dialect), recomputes `header_signature`
   from the **parsed header row** (§2.4), applies the mapping row-by-row, saves
   the profile (§2.4), and renders the summary (§2.5).

Because the signature is derived from the *parsed* header row (post
`csv.reader`), not the raw bytes, it is unaffected by the browser's CRLF↔LF
normalisation or a stripped trailing newline in the carried textarea — the
Upload and Apply screens provably compute the same signature.

### 2.2 Mapping pre-fill precedence

Each `map_<i>` select is pre-selected by, in order:

1. **Saved profile** — a mapping previously chosen for this exact header layout
   (§2.4).
2. **Name guess** — case-insensitive match of the header against an alias table
   (`name`→Name; `first name`/`last name`→Name, §2.3; `type`/`category`→Type;
   `email`/`e-mail`/`email address`→Email; `phone`/`mobile`/`tel`/`phone 1`→
   Phone; `notes`/`note`→Notes). Unmatched headers default to Ignore.
3. **Ignore**.

Only the pre-selection is automatic; the user reviews and can change every
select before importing.

### 2.3 Multi-value, name assembly, and label sanitising

- **Name.** One column → Name uses its value. Two+ columns → Name (e.g.
  `First Name` + `Last Name`) join their non-empty values with a single space in
  source-column order.
- **Extra Email / Phone.** The contact holds one email and one phone. If more
  than one column maps to Email (or Phone), the **first non-empty** value (in
  source-column order) becomes the contact's email/phone; each **additional**
  non-empty value is stored as a custom field labelled `Email 2`, `Email 3`, …
  (`Phone 2`, …).
- **Custom-field labels are sanitised.** Any label from a source header (a
  column mapped to `Custom field`) or generated for an extra value is passed
  through a sanitiser: chars outside `[a-zA-Z0-9_ ]` → space, runs of spaces
  collapsed, trimmed, truncated to 64. Empty result → `Field <n>`. The sanitised
  label MUST pass `valid_field_name` (`models.py:338`; regex `_FIELD_NAME_RE =
  ^[a-zA-Z0-9_ ]{1,64}$` at `models.py:335`) before use — nothing that fails it
  reaches `_validate_custom_field_names` (INV-4).

### 2.4 Learning — `import_profiles`

- New table (migration `004_import_profiles.sql`):
  ```sql
  CREATE TABLE IF NOT EXISTS import_profiles (
      header_signature TEXT PRIMARY KEY,
      mapping          TEXT NOT NULL,   -- JSON: {source_header: target}
      default_type     TEXT NOT NULL,
      updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
  );
  ```
- `header_signature` = SHA-256 hex of the parsed header list: each header
  `strip()`-ed and lower-cased, joined with `\x1f`, preserving source order.
  Fixed-size; one row per distinct layout.
- On **Apply**, upsert (`INSERT ... ON CONFLICT(header_signature) DO UPDATE`).
  On **Upload**, look up and use as top-precedence pre-fill (§2.2). Saved keys
  absent from the current file are ignored; current headers absent from the
  saved mapping fall through to name-guess.

### 2.5 Duplicate handling — additive update

For each parsed row, resolve a **match** against existing contacts:

1. If the row has a non-empty mapped email:
   `SELECT id FROM contacts WHERE email IS NOT NULL AND email != '' AND
   LOWER(email) = LOWER(?) ORDER BY id LIMIT 1`
   — reuses the `email IS NOT NULL AND email != ''` non-empty guard from
   `find_all_duplicates` (`models.py:196`) with a case-insensitive
   `LOWER(email) = LOWER(?)` compare; `ORDER BY id LIMIT 1` makes the winner
   deterministic since `contacts.email` is not unique.
2. Else (no mapped email, or it was blank), on the mapped name:
   `SELECT id FROM contacts WHERE name = ? COLLATE NOCASE ORDER BY id LIMIT 1`
   — the `COLLATE NOCASE` idiom from `find_duplicates` (`models.py:135`).

- **No match** → create a new contact.
- **Match** → **additive update only**: set a core field (email, phone, notes,
  type) on the existing contact **only if that field is currently NULL/empty**;
  never overwrite a non-empty value. Add a custom field **only if the existing
  contact has no custom field of that name** (case-insensitive, per
  `idx_cf_unique`, `migrations/002:17`).
- **Empty rows** (no mapped name and no mapped email) are skipped.

The summary reports: created N, updated M (listing updated names), skipped S
(blank), and per-row warnings (invalid type coerced to default; a label that
failed sanitising). This satisfies "advise the user the contact exists and only
new fields are imported."

### 2.6 Edge cases (CSV)

- **Ragged rows.** Fewer cells than headers → right-pad with empty strings; more
  cells → surplus ignored (`zip` against the header list).
- **Duplicate source headers.** Two columns sharing a header (e.g. two `Email`
  columns) are disambiguated **by appending ` <n>` for the 2nd+ occurrence**
  before use as a custom-field label: headers `Email`,`Email` → labels
  `Email`,`Email 2`. (This is the same numbering scheme as §2.3's extra-value
  labels, so a duplicate header mapped to `Custom field` and an extra value
  mapped to Email both yield `Email 2` — one consistent rule, and never a
  collision on `idx_cf_unique`.) The `header_signature` (§2.4) uses the raw
  ordered header list, so duplicate headers still yield a stable signature.
- **Encoding.** Decoded `utf-8-sig` (§2.1); non-UTF-8 flashes an error, not 500.
- **Malformed CSV.** `csv.Error` is caught and flashed.

### 2.7 Data-layer helper

`import_contact(db, fields: dict, custom_fields: list[tuple[str, str]]) ->
tuple[int, str]` in `models.py`: takes a parsed dict (deliberately — the
importer builds fields dynamically from the mapping, unlike `create_contact`'s
flat kwargs), resolves the match (§2.5), performs create-or-additive-update
atomically (`with db:`), and returns `(contact_id, 'created' | 'updated')`.
Reuses `_validate_contact_type` / `_validate_custom_field_names`.

## 3. vCard import & export (CL-0023)

New module `vcard.py` — a small hand-rolled parser and emitter. No dependency:
our record is one name + one email + one phone + custom fields, vCard 3.0 is a
line-based text format, and the popular lib (`vobject`) is heavier and lightly
maintained.

### 3.1 Export — `GET /contacts/export/vcard`

- Emits one `.vcf` for all contacts, `Content-Type: text/vcard`, filename
  `contacts.vcf`. Like the existing CSV export (`routes/contacts.py:160`,
  buffering via `io.StringIO`), the body is built in memory rather than streamed
  — a documented deviation from DESIGN §7.2 (see §7).
- **Export must load each contact's custom fields** (via `get_custom_fields`
  per contact, or an equivalent join). The existing `export_contacts`
  (`models.py:114`) selects core columns only and must **not** be reused as-is,
  or the `X-CL` lines — and INV-2 — are silently lost.
- Per contact (vCard **3.0**): `BEGIN:VCARD` / `VERSION:3.0` / … / `END:VCARD`.
  - Individuals: `FN:<name>` + `N:<name>;;;;`. Companies: `FN:<name>` +
    `ORG:<name>`.
  - `EMAIL:<email>`, `TEL:<phone>`, `NOTE:<notes>` when present.
  - **Every** custom field — including numbered `Email 2` / `Phone 2` extras
    (§2.3) — is emitted as `X-CL;X-LABEL=<name>:<value>`, never as an extra
    `EMAIL`/`TEL`. (This is what makes INV-2 hold: a numbered extra round-trips
    back to the same custom field, not a second primary value.) The property
    name is the fixed token `X-CL`; the original field name rides in the mandatory
    `X-LABEL` param (de-sanitising on import would be lossy, so the param is
    always emitted). Custom-field names are already constrained to
    `[a-zA-Z0-9_ ]`, so the `X-LABEL` value is all vCard param SAFE-CHARs (no
    `; : ,`) and needs no quoting or caret-escaping.
- Property **values** are escaped per RFC 6350/2426: `\`→`\\`, `,`→`\,`, `;`→
  `\;`, newline→`\n`. Lines are emitted unfolded — this round-trips through our
  own importer (INV-2) but is not guaranteed to interoperate with third-party
  readers that require ≤75-octet folding. Acceptable: export targets our own
  re-import.

### 3.2 Import — `POST /contacts/import` accepts `.vcf` too

The upload form (§2.1) offers both CSV and vCard. A `.vcf` upload (detected by
extension or a leading `BEGIN:VCARD`) skips the mapping screen — vCard is
self-describing — and `import_view` **imports it immediately on that single POST
and renders the summary**. This is deliberately asymmetric with CSV (which
previews first): vCard needs no field mapping, and additive import (§2.5) is
non-destructive, so there is nothing to preview-gate. CSRF is validated on this
POST like any other (§6).

- Parses vCard **3.0 and 4.0**. Unfolds continuation lines (leading space/tab
  continues the previous) first, then splits each `PROP;PARAMS:VALUE`.
- **Name.** `FN` → name; if no `FN`, assemble from `N`'s structured parts. A card
  with neither a usable `FN` nor `N` is **skipped and counted** in the summary
  (`contacts.name` is `NOT NULL`).
- **Type.** `company` iff the card has `KIND:org` (4.0) **or** an `ORG` property
  while the `N` given-name and family-name parts are both empty — where an
  **absent `N` line counts as both-parts-empty** (so an `FN`+`ORG`-only card is a
  company). Else `individual`. This is analogous to the Google-import heuristic
  (`google_sync.py:229-231`, CL-0010, which keys on People-API
  `givenName`/`familyName` — "an org with no personal name"); vCard has no such
  fields, so the predicate is defined here on `N`/`KIND`.
- **Values.** First `EMAIL` → email; first `TEL` → phone; `NOTE` → notes.
  Additional `EMAIL`/`TEL` → custom fields labelled `Email 2`, `Phone 2`, …
  (numbered + sanitised per §2.3 — never the raw `TYPE=` param, which may hold
  characters `valid_field_name` rejects).
- `X-CL` properties → custom fields, name from the `X-LABEL` param.
- Unescapes `\\ \, \; \n` in values.
- **Empty / zero-card file** → flash "No contacts found in the file."

## 4. Merge duplicates (CL-0024)

### 4.1 Entry point

`duplicates.html`'s existing bulk-select `<form>` (POST → `bulk_delete`,
`templates/duplicates.html:22`) gains a **"Merge selected"** button beside
"Delete selected". It is a plain submit button that overrides only the form's
`action` (keeping the form's default **POST** method):

```html
<button type="submit" formaction="{{ url_for('contacts.merge_preview') }}">
    Merge selected
</button>
```

This POSTs the whole form — the checked `selected` ids, plus the existing
`_csrf_token` and `ref` hidden fields — to `merge_preview`. **POST (not GET) is
deliberate:** it keeps the CSRF token in the request body, out of the URL /
browser history / referrer (a GET-serialised form would leak the token into the
query string). `_check_csrf` validates it like any POST (INV-5).

### 4.2 Merge preview — `POST /contacts/merge` (`merge_preview`, read-only)

Reads `request.form.getlist('selected')`. **Server-side guard:** requires
**2+ distinct** ids — 0 or 1 flashes "Select at least two contacts to merge."
and redirects back to the duplicates page. (There is no JS pre-check as there is
for delete, so this guard is the only gate.) The route performs no writes. It
renders `merge.html`:

- One row per core field (`name`, `type`, `email`, `phone`, `notes`): the
  distinct non-empty values among the selected contacts as radio options, the
  first pre-selected.
- **Custom fields** unioned by name, compared **case-insensitively** (so
  `Nickname`/`nickname` are one field, never two rows that would collide on
  `idx_cf_unique`). A name whose values differ becomes a radio group; a name
  unique to one contact carries as-is; a contact with zero custom fields
  contributes none.
- The **survivor** is the lowest-`id` (oldest) contact, stated on-screen; the
  rest are deleted on apply. `merge.html`'s own `<form method="post"
  action="{{ url_for('contacts.merge_apply') }}">` carries a fresh CSRF token,
  the chosen values, `survivor_id`, and the `loser_ids`.

### 4.3 Apply — `POST /contacts/merge/apply` (`merge_apply`)

`merge_contacts(db, survivor_id, loser_ids, fields, custom_fields)` in
`models.py`. To satisfy INV-3 (atomic) and INV-4 (validated) without duplicating
the write path, `update_contact`'s body is refactored into a private
`_write_contact(db, contact_id, type, name, email, phone, notes,
custom_fields)` helper (validators + `UPDATE` + custom-field replace, **no**
transaction wrapper). Then:

- `update_contact` becomes `with db: _write_contact(...)` (behaviour unchanged).
- `merge_contacts` runs one `with db:` block: guard that ids exist, are
  distinct, and `survivor_id ∉ loser_ids`; call
  `_write_contact(db, survivor_id, …chosen…)`; then `DELETE` each loser (custom
  fields cascade via the FK, `migrations/001:20`, with `PRAGMA foreign_keys=ON`,
  `db.py:34`). One `with db:` → atomic (no nested transaction; `_write_contact`
  has no wrapper of its own).

On success, redirect to the survivor's detail page with a success flash naming
how many were merged.

## 5. Data-model changes

Migration `004_import_profiles.sql` (§2.4). No change to `contacts` or
`custom_fields`. `db.init_db()` sorts and applies every `migrations/*.sql` once,
tracked in `schema_version` (`db.py:70-80`, dir at `db.py:66`); `004` is picked
up in order and must be idempotent (`CREATE TABLE IF NOT EXISTS`) — it is.

## 6. Security & robustness

- **Upload cap.** Add `MAX_CONTENT_LENGTH = 5 * 1024 * 1024` to the `Config`
  class in `config.py` (picked up via `app.config.from_object(Config)` in
  `create_app`, `app.py:19`); an oversize request gets Flask's 413 before any
  handler runs. This hard ceiling covers both the file upload and the
  carried-CSV re-post. In addition, the upload handler rejects a **decoded body
  larger than 1 MiB** with a flashed error, so the carried `csv_text` re-post
  (§2.1) stays well under `MAX_CONTENT_LENGTH` regardless of escaping. Both
  bounds are tested (§8).
- **CSRF.** The new POST endpoints — `import_view` (POST), `import_apply`,
  `merge_preview`, `merge_apply` — all carry the signed token in the body,
  validated by the blanket `_check_csrf` before-request hook (`app.py:63-68`,
  fires on every POST/PUT/DELETE, no exemptions). The GET endpoints
  (`import_view` GET form, `export_vcard`) are read-only and need no token.
- **XSS.** All imported values render through Jinja2 autoescaping; preview,
  mapping, merge, and summary use no `Markup()`.
- **File-type branch.** `.vcf` / leading `BEGIN:VCARD` → vCard path; else CSV.
  Malformed files flash a specific error (catch `csv.Error`,
  `UnicodeDecodeError`, and vCard parse errors — no bare `except`), never 500.
- **CSV injection on import is not applicable** (we read, not execute). Export
  behaviour is unchanged (not in scope).

## 7. New / changed files & size budget

- **New:** `vcard.py`, `templates/import.html`, `templates/merge.html`,
  `migrations/004_import_profiles.sql`.
- **Changed:** `routes/contacts.py` (the five routes in §1.1 + CSV mapping),
  `models.py` (`import_contact`, `merge_contacts`, `_write_contact` extraction,
  profile get/save, a vCard-export query that includes custom fields — §3.1),
  `config.py` (`MAX_CONTENT_LENGTH`),
  `templates/duplicates.html` (merge button), `templates/base.html` (Import nav
  link), the import page (vCard export link).
- **DESIGN.md — already edited in this change-set (not merely planned):**
  - §14 file budget — Python cap raised `< 50 KB` → `< 80 KB`, labelled a **soft
    target**, scoped to shipped app `.py` **excluding `tests/`**, with a
    back-reference to this spec. (Shipped app source is ~58 KB today, excluding
    `tests/`; these features add ~15–20 KB.)
  - §13 version plan — the v1.1 row now reads "CSV import, vCard import/export,
    merge duplicates".
- **DESIGN §7.2 streaming deviation.** §7.2 asks CSV/vCard export to stream via
  generators; both the existing CSV export and this vCard export buffer in
  memory. Rationale (per DESIGN's "deviations require a documented rationale"):
  single-user scale, a ≤10k-contact ceiling (§7.1) keeps the buffer small, the
  5 MiB cap bounds it, and it matches the existing CSV export. Revisit if a
  larger-scale mode is added.

## 8. Testing (per DESIGN.md §11)

- **`vcard.py` units:** emit → parse → all fields + custom fields round-trip
  (via `X-CL`/`X-LABEL`, incl. a numbered `Email 2` extra that round-trips as a
  custom field, not a second `EMAIL`); parse a real-world 3.0 and a 4.0 sample;
  multi-`TEL`/`EMAIL` → numbered custom fields that pass `valid_field_name`;
  value escaping of `,;\`+newline; line-unfolding; a card with no `FN`/`N` is
  skipped; an empty file imports nothing.
- **CSV import units:** mapping applies; two Name columns join; an extra Email
  column → `Email 2` custom field; duplicate `Email` headers → `Email`/`Email 2`
  labels with no `idx_cf_unique` violation; a header with illegal chars is
  sanitised to a valid label; additive update fills only blank fields and never
  overwrites; a blank mapped email falls through to the name match; a
  case-insensitive custom-field name is not re-added; ragged rows padded;
  `utf-8-sig` BOM stripped; blank rows skipped; profile saved then pre-fills on
  the same header signature.
- **Merge units:** `merge_contacts` updates survivor, deletes losers **and their
  custom fields (cascade)**, unions custom fields (case-insensitive, no
  `idx_cf_unique` violation), rejects `survivor ∈ losers` and <2 ids; a forced
  mid-merge failure leaves survivor + all losers unchanged (INV-3 rollback);
  `_write_contact` reuse keeps `update_contact` behaviour unchanged.
- **Route tests:** `/contacts/import` (CSV mapping + vcf immediate-import)
  end-to-end; `merge_preview` renders and rejects <2 selected; `merge_apply`
  merges; **a CSRF-missing POST to each of `import_view`, `import_apply`,
  `merge_preview`, and `merge_apply` is rejected**; an upload over
  `MAX_CONTENT_LENGTH` → 413, and a decoded body over 1 MiB → flashed error.

## 9. Invariants

- **INV-1.** Additive import never overwrites an existing non-empty core field or
  an existing custom-field name.
- **INV-2.** A vCard produced by export, re-imported into an empty DB, reproduces
  the same contacts and custom fields. (Lossless because custom-field names are
  constrained to `valid_field_name`, and every custom field — including numbered
  extras — round-trips via `X-CL`/`X-LABEL`, never as a second `EMAIL`/`TEL`.)
- **INV-3.** Merge is atomic: on any failure survivor and all losers are left
  exactly as before (single `with db:` block).
- **INV-4.** No import/merge value bypasses `_validate_contact_type` /
  `_validate_custom_field_names`; every generated or derived custom-field label
  passes `valid_field_name` first.
- **INV-5.** Every new POST route validates CSRF via `_check_csrf`.

## 10. Out of scope

- Two-way / write-back sync (CL-0033), contact photos (CL-0026), groups/tags.
- CSV/vCard *streaming* for huge files (§7 deviation) — single-user scale; the
  size cap covers abuse.
- Column-mapping for vCard (self-describing) and a JSON API.
