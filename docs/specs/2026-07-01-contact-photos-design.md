# Contact Photos / Avatars — Design (CL-0026)

Status: Implemented (v1.2). Passed `/cold-eyes` — 5 loops, 15 independent
reviews, zero Critical throughout; findings decayed from real contract errors
(loop 1) → a real bug caught (loop 3: photo cap vs the 5 MiB request ceiling) →
a real layout risk (loop 4: photo in the JS masonry) → wording polish (loop 5).
All verified findings fixed; no fix regressed.
Date: 2026-07-01
Amends DESIGN.md in the same change-set as the implementation (all § below are
**DESIGN.md** sections; references to this spec's own sections say "this spec's"):
- **§6.1** — relaxes the mandatory rule "File uploads: **None allowed** in v1" to
  a validated local-photo upload (policy in this spec's §3).
- **§7.3** — supersedes the "Image/avatar storage (link to URLs if needed, don't
  store blobs)" avoidance: this feature stores photo **files on disk** (never
  blobs in the DB) and serves them locally; rationale in this spec's §1/§3.
- **§9** — adds the photo route to the route table.
- **§13** — its version table (v1.0 / v1.1 / v2.0 / v2.1 / v3.0) has no v1.2; adds
  a **v1.2** row for contact photos between v1.1 and v2.0. (v1.1's own scope —
  CSV/vCard/merge — is still `[Unreleased]`, so this ordering assumes v1.1 cuts
  first; see the *Version label* note below.)
- **§14** — file-size budget; see this spec's §10 (and the pre-existing-drift note
  there).

The **Dependency Budget** sub-block of DESIGN.md §3 (Technology Stack) is
*unchanged* — this feature adds no pip package. That sub-block also states "No
C-extension dependencies beyond what ships with Python", which is why Pillow (an
external C-extension) is out.

**Version label:** planned as **v1.2**. Whether photos ships as its own v1.2 or is
folded into the next combined release is a release-time call for the maintainer
(raised separately) — it does not affect any code in this spec.

Sections: [1 Overview](#1-overview) · [2 Storage & data model](#2-storage--data-model) ·
[3 Image validation](#3-image-validation-no-new-dependency) · [4 Google sync](#4-google-sync-photos) ·
[5 Upload & remove](#5-upload--remove-manual) · [6 Serve route](#6-serve-route) ·
[7 Display](#7-display) · [8 Deletion & merge cleanup](#8-deletion--merge-cleanup) ·
[9 Security](#9-security--robustness) · [10 Files & size budget](#10-new--changed-files--size-budget) ·
[11 Testing](#11-testing) · [12 Invariants](#12-invariants) · [13 Out of scope](#13-out-of-scope).

## 1. Overview

Give each contact an optional real photo, replacing the coloured-initial circle
where one exists. Two sources:

- **Google sync** — the People API returns a photo URL per contact; on sync the
  app downloads a real (non-default) photo once and stores it locally.
- **Manual upload** — a file picker on the Add/Edit contact form.

Photos are stored as files in a private per-user directory and served by the app
itself from its own origin. **No CSP directive is added or removed** — the CSP
string stays exactly as it is: `default-src 'self'` already covers `img-src`, and
same-origin images need no new directive. Choosing local storage over hot-linking
Google's servers is what keeps the CSP strict and makes photos work offline. This
implements CL-0026 in `ROADMAP.md`: its option (b) (local storage) *plus* its
separate "Also allow local upload" clause.

Single-user, localhost only. Reuses the existing data-access layer (`models.py`),
the migration runner (`db.py`), and the private-dir helper (`config.py`). **No new
pip dependency** (§3).

## 2. Storage & data model

### 2.1 On-disk layout

- Directory: `~/.config/contact-list/photos/` (the value of `PHOTOS_DIR`, added to
  the `Config` class in `config.py` — this spec's §10). Created `0700` by calling
  `ensure_private_dir(app.config['PHOTOS_DIR'])` inside `create_app` in `app.py`,
  immediately after the existing `with app.app_context(): init_db()` block
  (app.py:33-34) and before the `log.info('App initialized …')` line — the same
  helper that protects the Google token dir (CL-0011). (`ensure_private_dir` is currently called only from
  `google_sync` on token save and `config` on secret-key persist; this adds an
  explicit startup call.)
- File name: `<contact_id>.<ext>` where `<ext>` ∈ {`jpg`, `png`, `gif`, `webp`}.
  The id is an integer from the DB and the ext is from our own allow-list (§3) —
  **no user-supplied filename ever touches the path.**
- One photo per contact. Replacing a photo overwrites; because the extension can
  change (png → jpg), the writer deletes any pre-existing `<contact_id>.*` for
  that contact before writing the new file (it reads the old ext from the DB row,
  §2.2, and unlinks that exact file).

### 2.2 Database — new `contact_photos` table

A separate table, **not** a new column on `contacts`. Rationale: the migration
runner (`db.py:init_db`) requires every migration to be idempotent (re-runnable
after a crash between `executescript` COMMIT and the `schema_version` INSERT).
SQLite supports `CREATE TABLE IF NOT EXISTS` but has no `ADD COLUMN IF NOT
EXISTS`, so a column migration could not satisfy that rule. A table also mirrors
the existing `custom_fields` pattern and auto-removes its row on contact delete
via `ON DELETE CASCADE`.

`migrations/005_photos.sql`:

```sql
CREATE TABLE IF NOT EXISTS contact_photos (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    ext         TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

`005` is the next free migration number (existing: `001`–`004`). Migrations run in
`sorted()` filename order (`db.py`), so if the still-unreleased v1.1 set adds a
migration before this ships, re-check that `005` is still the highest number and
renumber if not.

`PRIMARY KEY` on `contact_id` enforces one photo per contact. `ext` is the
stored file extension so the serve route knows the MIME type without sniffing
disk. Foreign-key cascade requires `PRAGMA foreign_keys = ON`, which `db.py`
(`get_db`) sets on every connection — verified. The §8 delete-cleanup also
removes the file explicitly, so the cascade is defence-in-depth for the DB row,
not the sole cleanup path.

### 2.3 Data-access helpers (`models.py`)

- `set_contact_photo(db, contact_id, ext)` — upsert (`INSERT … ON CONFLICT
  (contact_id) DO UPDATE SET ext = excluded.ext, updated_at = …`).
- `get_contact_photo_ext(db, contact_id) -> str | None` — the stored ext or None.
- `clear_contact_photo(db, contact_id)` — delete the row (returns the old ext, if
  any, so the caller can unlink the file).

`list_contacts` (via `_build_contact_query`) gains a `has_photo` flag per row so
the list template can decide img-vs-initials without an N+1 query.
`_build_contact_query` selects an **explicit named column list** (`SELECT id,
type, name, email, phone, notes, created_at, updated_at FROM contacts …`), *not*
`SELECT *`, so the new flag is appended to that list as a correlated `EXISTS`
subquery column. It must not add a JOIN (which would fan out rows and break the
existing `COUNT(*)`-over-subquery total, the same constraint that shaped
CL-0025):

```sql
SELECT id, type, name, email, phone, notes, created_at, updated_at,
       EXISTS (SELECT 1 FROM contact_photos p WHERE p.contact_id = contacts.id) AS has_photo
FROM contacts …
```

Splice the `has_photo` column into the **static `SELECT … FROM contacts` prefix**
inside `_build_contact_query` (models.py) — before the dynamic `WHERE` clauses and
bound params the helper appends, and before the `ORDER BY` / `LIMIT` / `OFFSET`
that `list_contacts` adds after the helper returns. All of those are unaffected:
the scalar `EXISTS` column adds no param and touches neither row count nor
ordering. Each row then exposes `c.has_photo` (0/1) to the template.

`get_contact` already returns the full `contacts` row; the **detail** route reads
the ext via `get_contact_photo_ext` and passes it to the template as `photo_ext`
(a truthy ext string, or `None`) — the detail template branches on `photo_ext`,
the list template on `has_photo`.

## 3. Image validation (no new dependency)

New module `photos.py` (file I/O + validation; DB access stays in `models.py`,
mirroring how `google_sync.py`/`phoneutil.py` sit beside `models.py`).

> **Superseded in part by CL-0035 (2026-07-04):** Pillow *was* subsequently added,
> for photo thumbnailing — see `docs/specs/2026-07-04-photo-thumbnails-design.md`.
> The magic-byte allow-list below remains the validation gatekeeper; Pillow only
> decodes bytes that already passed it, and the security trade-off is re-examined
> in that spec's §6. The "no image library" reasoning here is the historical
> rationale, retained for context.

**Why no image library (e.g. Pillow):** decode-and-re-encode is the gold standard
for stripping hostile payloads, but it adds a large C-extension codec surface —
itself a historical source of image-parsing CVEs — for marginal benefit in a
**single-user localhost** tool where the uploader is the operator. Instead, for a
threat model of "a disguised or malformed file gets stored and served back":

1. **Magic-byte allow-list** — accept only files whose leading bytes match a real
   JPEG / PNG / GIF / WebP signature; map the signature (not any client-supplied
   name or content-type) to the stored ext. Everything else is rejected, **SVG
   explicitly included** (SVG is the one raster-ish type browsers execute script
   from).
2. **Size cap** — reject when `len(data) > MAX_PHOTO_BYTES` where
   `MAX_PHOTO_BYTES = 4 * 1024 * 1024` (4 MiB, ≈4 MB). The comparison is strictly
   greater-than, so a file of *exactly* 4 MiB is accepted; one byte more is
   rejected. The cap sits **deliberately below the existing app-wide request
   ceiling** `MAX_CONTENT_LENGTH = 5 * 1024 * 1024` (5 MiB, already set at
   `config.py:86`): Flask returns a bare `413` for any request body over that
   ceiling *before* the view runs, so keeping the photo cap under it — with
   headroom for multipart form overhead — means an oversize upload reaches our
   friendly in-handler `ValueError` flash (§5) instead of a raw 413. The separate,
   tighter 1 MiB inner cap on decoded import bodies (`MAX_IMPORT_BYTES`,
   `config.py:87`) is unrelated and untouched. Enforced by a byte-length check in
   `photos.py`. The user-facing flash (§5) says "under 4 MB" — a deliberate
   friendly rounding of the exact 4 MiB (`4,194,304`-byte) constant.
3. **Served safely** — the serve route (§6) sets an explicit image `Content-Type`
   from the stored ext, and the global `X-Content-Type-Options: nosniff` +
   `default-src 'self'` mean a mislabelled/polyglot file cannot be re-interpreted
   as HTML or script by the browser. The path is built from an int id + our own
   ext, so no traversal.

Signature table. JPEG/PNG/GIF are a **prefix** match on the raw bytes; **WebP is
not a prefix match** — a RIFF container (`.wav`, `.avi` also start `RIFF`) is only
WebP when bytes 8–11 spell `WEBP`, so both offsets must be checked:

| Type | Check | ext |
|------|-------|-----|
| JPEG | `data[:3] == FF D8 FF` | `jpg` |
| PNG  | `data[:8] == 89 50 4E 47 0D 0A 1A 0A` | `png` |
| GIF  | `data[:4] == 47 49 46 38` (`GIF8`) | `gif` |
| WebP | `data[:4] == 52 49 46 46` (`RIFF`) **and** `data[8:12] == 57 45 42 50` (`WEBP`) | `webp` |

`detect_image_ext(data: bytes) -> str | None` returns the ext or None (reject).
It must tolerate inputs shorter than the longest signature (12 bytes) — a slice
that runs past the end simply won't match, so short/empty input returns None
rather than raising. `save_photo(config, contact_id, data, *, old_ext) -> str`
validates **size first** (§3 item 2, the size cap) **then magic bytes** — so an
oversize non-image is rejected as oversize, and the sync path's `MAX_PHOTO_BYTES +
1` read (§4) is always caught by the size check before content inspection. It then
deletes `photos/<id>.<old_ext>` if `old_ext` is given, writes the new file, returns
the new ext; raises `ValueError` (specific exception) on any reject. Callers
translate that into a flashed message / skipped sync photo. Here `config` is the
Flask app config (dict-like `app.config`) — the same `config` object
`sync_contacts` receives and passes to `_load_credentials`, which reads
`config['GOOGLE_TOKEN_FILE']`; `save_photo`/`delete_photo` read the directory as
`config['PHOTOS_DIR']` (added to the `Config` class in `config.py`, §10).

## 4. Google sync photos

`sync_contacts` adds `photos` to `personFields`:

```
names,emailAddresses,phoneNumbers,organizations,biographies,birthdays,addresses,photos
```

`_upsert_person` gains a trailing `config` parameter so it can reach the photos
dir. The signature changes from `_upsert_person(db, person, region)` to
**`_upsert_person(db, person, region, config)`**, threaded from `sync_contacts`
(signature `sync_contacts(config, db, region)`, which already holds `config`).
The existing test call-sites `google_sync._upsert_person(db, person, 'US')`
(`tests/test_hardening.py:77` and `:89`) must be updated to pass `config` — a
required change in the same commit, or those tests break. After the contact row
is written and its id known, for the person's photos:

- Take the first entry in `person['photos']` **whose `default` is not true** —
  the People API flags its generated grey silhouette with `"default": true`, and
  storing that would be worse than the app's own initials avatar.
- Only fetch when `url` is present, `https`, and the host ends with
  `googleusercontent.com` (the People API's photo CDN). This bounds the fetch to
  Google's own servers — the sync payload is already authenticated, this guards
  against a malformed record pointing the downloader elsewhere (SSRF defence).
- Download with `urllib.request` (stdlib — no `requests` dependency) under a short
  timeout (10 s), read at most `MAX_PHOTO_BYTES + 1` bytes, then run the same
  `save_photo` validation + `set_contact_photo`. The `+1` is deliberate: reading
  one byte past the cap means a body larger than the cap yields
  `len == MAX_PHOTO_BYTES + 1` and is rejected by the size check. Reading only
  `MAX_PHOTO_BYTES` would make an oversize body indistinguishable from an
  exactly-at-cap one and silently store a truncated image — do **not** do that.
- A photo failure (network, oversize, non-image) is **non-fatal**: log at
  `warning`, leave the contact photo-less, continue. Sync's per-contact SAVEPOINT
  already isolates DB failures; the photo download is wrapped in its own
  `try/except` so it cannot abort the contact import.

Re-sync is idempotent: `save_photo` overwrites and `set_contact_photo` upserts.
(v1.2 always re-downloads a present non-default photo; it does not diff Google's
photo etag — acceptable, photos are small and sync is user-initiated. Noted §13.)

## 5. Upload & remove (manual)

`contact_form.html` (shared by Add and Edit):

- `<form … enctype="multipart/form-data">` (currently urlencoded — this attr is
  required for the file part).
- `<input type="file" name="photo" accept="image/jpeg,image/png,image/gif,image/webp">`.
- On the Edit form only, when the contact already has a photo: a thumbnail preview
  and a `<input type="checkbox" name="remove_photo" value="1">` "Remove photo".

`routes/contacts.py` `create` and `update`:

- After the contact is created/updated and its id is known, if
  `request.files.get('photo')` has a non-empty filename, read its bytes and call
  `photos.save_photo(...)` + `models.set_contact_photo(...)`. On `ValueError`,
  flash "Photo must be a JPEG, PNG, GIF or WebP under 4 MB." and still save the
  rest of the contact (photo is optional, not a form-blocking error). A single
  flash string intentionally covers both reject causes (wrong format and
  oversize); `save_photo` raises a plain `ValueError` without sub-typing the two.
- On `update`, handle the upload branch **first**: if a non-empty `photo` file is
  present, store it and **ignore `remove_photo`** (the upload wins — a new file
  was explicitly chosen). Only when no new file is present and `remove_photo` is
  ticked, call `clear_contact_photo` and unlink the file. Spelling out this order
  avoids the trap where processing `remove_photo` after the upload would delete
  the file just written.
- CSRF: the form already carries `_csrf_token`; unchanged. The existing validated
  token covers the multipart POST.

## 6. Serve route

New route on the `contacts` blueprint:

| Method | Path | Endpoint | Purpose |
|--------|------|----------|---------|
| GET | `/contacts/<int:contact_id>/photo` | `contacts.photo` | Stream the stored photo |

(Plural `/contacts/…` matches every existing route on the blueprint — e.g.
`/contacts/<int:contact_id>`, `/contacts/<int:contact_id>/edit` — and DESIGN.md
§9.)

- Look up the ext via `get_contact_photo_ext`; if none, `abort(404)`.
- Serve with **`send_from_directory(app.config['PHOTOS_DIR'],
  f"{contact_id}.{ext}")`** (one API, not `send_file`). The filename is assembled
  from an int id + our own allow-listed ext, never from request input, and
  `send_from_directory` rejects any path escaping the base dir — so there is no
  path-traversal vector. It also raises `NotFound` (404) on its own if the DB row
  exists but the file was removed (manual tampering), so **no extra `os.path.exists`
  check is needed** — the helper handles the missing-file 404.
- The template only emits the `<img>` when `has_photo`, so 404s are not hit in
  normal flow; the fallback is purely defensive.

## 7. Display

The coloured-initial circle stays as the fallback everywhere. Where a photo
exists:

- **List (`contacts.html`)** — the `.avatar` span becomes
  `<img class="avatar" src="{{ url_for('contacts.photo', contact_id=c.id) }}"
  alt="" loading="lazy">` when `c.has_photo`, else the existing initials span.
  **Card view reuses the same `<tr>` rows** — but note card view is **not** pure
  CSS: `static/app.js` positions each card with **JS absolute positioning**,
  measuring card height *after* the view toggle (commit `1ae376b`). A photo whose
  height was unknown until it decoded could shift a row after that measurement and
  break the masonry layout. **Guard (mandatory):** `img.avatar` must carry
  **explicit fixed CSS width/height** (the same box as the initial circle, below),
  so the avatar occupies a known box immediately and its image load — lazy or not —
  never changes row height. *Acceptance:* toggling to card view for contacts with
  photos produces no overlapping or gapped cards after the images finish loading.
- **Detail (`contact_detail.html`)** — a larger photo at the top when present
  (the detail template branches on `photo_ext`), else the existing initial. The
  detail page is not masonry, so its photo has no layout constraint.
- **CSS (`static/style.css`)** — an `img.avatar` rule with a **fixed** width/height
  (same box as the initial circle), `object-fit: cover`, `border-radius` to match.
  One detail-size rule.

## 8. Deletion & merge cleanup

The DB row is handled by `ON DELETE CASCADE`; the **file** is not, so callers
unlink it explicitly:

- `delete` and `bulk_delete` — before/after deleting each contact, unlink
  `photos/<id>.*` (via the stored ext from `get_contact_photo_ext`, read before
  the DB delete). A missing file is ignored.
- `merge_apply` — `merge_contacts(db, survivor_id, loser_ids, fields,
  custom_fields=None)` deletes the losers. For each `loser_id`, unlink its photo
  file (read its ext before the delete). The **survivor (`survivor_id`) keeps its own** photo; if the survivor
  has none but a loser did, v1.2 does **not** adopt it (noted §13). This mirrors
  merge's existing "survivor's chosen fields win" model; adopting a photo would
  need a picker the merge screen doesn't have yet.

A tiny helper `photos.delete_photo(config, contact_id, ext)` centralises the
unlink (guards `ext is None`, ignores `FileNotFoundError`). `save_photo`'s own
"delete the old file before writing the new ext" step (§2.1, §3) **delegates to
this same `delete_photo`**, passing its `old_ext` as the `ext` argument — one
unlink implementation, so the `old_ext` (keyword-only on `save_photo`) and `ext`
(positional on `delete_photo`) refer to the same value.

## 9. Security & robustness

| Concern | Mitigation |
|---------|------------|
| Script-carrying upload (SVG, polyglot) | Magic-byte allow-list rejects SVG and anything non-{JPEG,PNG,GIF,WebP}; served with explicit image MIME + global `nosniff` + `default-src 'self'` so the browser can't execute it (§3). |
| Path traversal | File path = private dir + int id + own-allow-list ext. No request-supplied filename or path segment used. |
| SSRF on sync download | Only fetch `https` URLs whose host ends `googleusercontent.com`; short timeout; capped read (§4). |
| Decompression bomb | 4 MiB byte cap before store; the browser (not the app) decodes; single-user localhost bounds blast radius. Noted as accepted residual risk. |
| Secret leakage | Photos are not secrets, but live under `~/.config/contact-list/` `0700` beside tokens; never in the repo or DB (only the ext string is in the DB). `.gitignore` already covers the config dir; no repo change needed. |
| CSP regression | None — same-origin serving adds/removes no CSP directive, so the CSP string is unchanged; both CSP tests (`tests/test_routes.py:404` `test_csp_header` and `tests/test_hardening.py:226` `test_style_src_has_no_unsafe_inline`) still hold. |
| CSRF | Upload rides the existing validated `_csrf_token` on the contact form POST. |

## 10. New / changed files & size budget

| File | Change | Est. LOC |
|------|--------|----------|
| `migrations/005_photos.sql` | new — `contact_photos` table | ~6 |
| `photos.py` | new — `detect_image_ext`, `save_photo`, `delete_photo`, `MAX_PHOTO_BYTES` | ~70 |
| `config.py` | add `PHOTOS_DIR`; ensure it `0700` at startup | ~5 |
| `models.py` | `set_contact_photo`, `get_contact_photo_ext`, `clear_contact_photo`; `has_photo` in list query | ~30 |
| `google_sync.py` | `photos` personField; download+store in `_upsert_person` (+`config` param) | ~35 |
| `routes/contacts.py` | `photo` serve route; upload/remove in create/update; unlink on delete/bulk_delete/merge | ~55 |
| `templates/contact_form.html` | multipart enctype, file input, remove checkbox + preview | ~15 |
| `templates/contacts.html` | img-or-initials in the avatar cell | ~5 |
| `templates/contact_detail.html` | larger photo when present | ~8 |
| `static/style.css` | `img.avatar` + detail photo rules | ~12 |
| `app.py` | `ensure_private_dir(app.config['PHOTOS_DIR'])` in `create_app`, beside `init_db()` | ~2 |

No new pip dependency — direct runtime deps stay at **6** (budget < 8 per the
**Dependency Budget, DESIGN.md §3**, which also bans non-stdlib C-extension deps).
`urllib.request` and the magic-byte check are stdlib. (This §10 table itself feeds
the file-size budget, DESIGN.md §14.)

**§14 file-size budget — pre-existing drift.** As of this writing DESIGN.md §14's
CSS/JS/template caps are **already exceeded, before this feature**: `static/style.css`
is >2× its 15 KB cap, `static/app.js` >2× its 10 KB cap, and `templates/` total
~1.4× its 30 KB cap — the caps went stale as the card-view/masonry work landed and
were never revised (verify the exact sizes at implementation time). This feature
adds only ~12 LOC CSS and ~28 template LOC on top, so it does not *materially*
change that picture, but it must not claim headroom that doesn't exist: the §14
CSS/JS/template caps are a stale-gate the maintainer should re-baseline (surfaced
separately, out of this spec's scope). There is **no JS change** (card view reuses
the existing `.masonry` code). The shipped Python source is under the < 100 KB
*soft* target with comfortable headroom; the ~245 new LOC this table sums to keep
it under — measure before landing.

## 11. Testing

Test-first (TDD), following the existing `tests/` fixtures (`app`, `db`,
`client`, `_get_csrf`). New `tests/test_photos.py` plus additions to
`test_models.py` / `test_routes.py` / `test_hardening.py`:

- **`detect_image_ext`** — each of JPEG/PNG/GIF/WebP signatures → correct ext;
  **both `GIF87a` and `GIF89a`** headers → `gif` (the 4-byte `GIF8` check covers
  both variants); a text blob, an SVG (`<svg…`), a RIFF-but-not-WebP blob
  (`RIFF….WAVE`), and empty / <12-byte input → None (no exception).
- **`save_photo`** — writes `<id>.<ext>`; `MAX_PHOTO_BYTES + 1` raises
  `ValueError`; **exactly `MAX_PHOTO_BYTES` is accepted** (boundary — `>` not
  `>=`); a png-then-jpg replace deletes the old `<id>.png`.
- **models** — `set`/`get`/`clear` round-trip; `list_contacts` sets `has_photo`
  true only for contacts with a row; `has_photo` does not inflate `total`
  (guards the no-JOIN constraint) — mirror CL-0025's dedup test.
- **serve route** — returns the bytes + an `image/*` content-type for a contact
  with a photo; 404 for one without; 404 when the DB row exists but the file was
  removed.
- **upload** — POST create/update with a small valid PNG stores it and the detail
  page renders an `<img>`; a `.txt` masquerading as `.png` (wrong magic bytes) is
  rejected with the flash and the contact still saves; `remove_photo` clears it.
- **delete/merge** — deleting a contact unlinks its file; merge unlinks the
  non-survivor's file and leaves the survivor's intact.
- **sync** — a People payload with a real photo stores it; one with
  `"default": true` stores nothing; a non-googleusercontent URL is skipped; a
  download error leaves the contact imported and photo-less (monkeypatch the
  fetch — no real network in tests).
- **hardening/CSP** — both `test_csp_header` (`tests/test_routes.py:404`) and
  `test_style_src_has_no_unsafe_inline` (`tests/test_hardening.py:226`) unchanged
  and still pass (no CSP edit).

## 12. Invariants

- **INV-1** — No request-supplied string is ever used in a photo file path; the
  path is `PHOTOS_DIR / f"{int_id}.{allowlisted_ext}"`.
- **INV-2** — Only {JPEG, PNG, GIF, WebP} by magic bytes are ever stored; SVG and
  all other types are rejected.
- **INV-3** — This feature adds and removes no CSP directive; the CSP string is
  unchanged (verified by the two existing CSP tests — §11).
- **INV-4** — `has_photo` in `list_contacts` never changes the row count or the
  paginated `total` (no JOIN; `EXISTS` subquery only).
- **INV-5** — A photo download/validation failure during sync never aborts the
  contact import; the contact is stored photo-less.
- **INV-6** — Sync stores a Google photo only when it is non-`default` and comes
  from an `https` `*.googleusercontent.com` URL.
- **INV-7** — Deleting or merging a contact leaves no orphaned photo file for the
  removed contact id.

## 13. Out of scope (v1.2)

- **Recently-viewed avatars** stay initials-only (that list is built client-side
  from localStorage names, not photo data).
- **Photo etag diffing on re-sync** — v1 re-downloads a present non-default photo
  each sync rather than comparing Google's photo metadata.
- **Merge photo adoption** — a survivor with no photo does not inherit a
  merged-away contact's photo (no picker for it yet).
- **Image cropping/resizing/thumbnails** — the browser scales via CSS
  `object-fit`; no server-side resizing (that is what a Pillow-class dependency
  would be for, deliberately deferred). *(Delivered later by CL-0035, 2026-07-04:
  server-side 256 px thumbnails via Pillow — see
  `docs/specs/2026-07-04-photo-thumbnails-design.md`.)*
- **Cache headers / ETag on the serve route** beyond the framework defaults from
  `send_from_directory` (§6).
