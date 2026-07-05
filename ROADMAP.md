# Contact List — Roadmap

Forward-looking work for Contact List. Status legend: 📋 planned · 🚧 in-progress ·
✅ shipped · 💭 considered. Each actionable bullet carries a stable `[CL-NNNN]` id.

See [DESIGN.md](DESIGN.md) for the architecture, data model, and the security /
efficiency / coding standards every item must comply with.

## Planned Features

- ✅ [CL-0001] **Add a Settings page.**
  Foundation for the per-user preferences below. Single-user app, so persist settings in a small settings table (or a JSON file in the config dir) and load them into app config / template context. Add a /settings route + nav link.
  **Layman:** A dedicated page where you can change how the app looks and behaves.
  Kind: feature.
  Source: user-request-2026-06-30.
  Resolved (2026-07-01): Settings page shipped on feat/settings-page (subagent-driven build, 98/98 tests, whole-branch review clean).

- ✅ [CL-0002] **Let the user pick their timezone on the Settings page.**
  Timestamps are stored ISO-8601 UTC (correct). Add a timezone preference and convert for display in the friendly_date filter. Depends on the Settings page.
  **Layman:** Show dates and times in your own timezone instead of UTC.
  Kind: feature.
  Source: user-request-2026-06-30.
  Resolved (2026-07-01): timezone preference applied in friendly_date.

- ✅ [CL-0003] **Let the user choose their preferred date format on the Settings page.**
  Drive the friendly_date Jinja filter (app.py) from a stored format preference instead of the hardcoded '%d %b %Y, %H:%M'. Depends on the Settings page.
  **Layman:** Choose how dates look, e.g. 30 Jun 2026 vs 06/30/2026.
  Kind: feature.
  Source: user-request-2026-06-30.
  Resolved (2026-07-01): date-format preference (DATE_FORMATS) applied in friendly_date.

- ✅ [CL-0004] **Add theme options (light/dark/color schemes).**
  Partial groundwork exists (a theme-init script + data-theme-choice hooks in static/app.js). Formalise it on the Settings page with persistence and a CSS-variable palette. Keep CSP-compatible (no inline script).
  **Layman:** Switch between light and dark mode and pick an accent colour.
  Kind: feature.
  Source: user-request-2026-06-30.
  Resolved (2026-07-01): theme now server-rendered from settings; browser-only theme JS removed.

- ✅ [CL-0005] **Add layout options (density / list vs card view).**
  Per-user layout preference applied via a body class + CSS. Depends on the Settings page.
  **Layman:** Choose a compact or roomy layout, and list or card view for contacts.
  Kind: feature.
  Source: user-request-2026-06-30.
  Resolved (2026-07-01): density + list/card layout via body classes.

- ✅ [CL-0006] **Make the default phone region a user setting.**
  DEFAULT_REGION is hardcoded to 'ZA' in routes/contacts.py and google_sync.py. Expose it as a setting so phonenumbers parses/formats for the user's country.
  **Layman:** Pick your country so phone numbers are understood and formatted correctly.
  Kind: enhancement.
  Source: in-session-2026-06-30 suggested.
  Resolved (2026-07-01): phone region is now a user setting, threaded into phoneutil.

- ✅ [CL-0007] **Add further user settings: contacts-per-page, default sort, default new-contact type.**
  CONTACTS_PER_PAGE already exists as a config constant; expose it plus default sort column/direction and default contact type on the Settings page.
  **Layman:** Small conveniences: contacts per page, default sort order, and whether new contacts default to person or company.
  Kind: feature.
  Source: in-session-2026-06-30 suggested.
  Resolved (2026-07-01): per-page, default sort/dir, and default new-contact type are settings consumed by the contact list & form.

- ✅ [CL-0022] **Import contacts from a CSV file.**
  Mirror the existing CSV export. Map Name/Type/Email/Phone/Notes columns and reuse create_contact + _validate_form + find_duplicates so imported rows get the same validation and duplicate warnings as manual entry.
  **Layman:** Let the user bring contacts in from a spreadsheet, not just export them.
  Kind: feature.
  Source: in-session-2026-07-01.
  Shipped 2026-07-01. CSV import with column-mapping + learned profiles (import_profiles), additive dedupe. Spec: docs/specs/2026-07-01-import-export-merge-design.md.

- ✅ [CL-0023] **Support vCard (.vcf) import and export.**
  Add a .vcf export alongside export_contacts, and a .vcf import path. vCard is the universal interchange format for phones/Apple Contacts/Thunderbird.
  **Layman:** Read and write the standard contact-card format that phones and mail apps use.
  Kind: feature.
  Source: in-session-2026-07-01.
  Shipped 2026-07-01. Hand-rolled vcard.py (3.0/4.0 parse, 3.0 emit), X-CL custom-field round-trip, no new dependency.

- ✅ [CL-0024] **Add a merge action to the duplicates page.**
  The duplicates page is read-only today. Add a merge: keep one contact, fold in the other's non-empty fields + custom_fields, then delete the loser. Wrap in a transaction.
  **Layman:** Let the user combine two duplicate contacts into one from the duplicates screen.
  Kind: feature.
  Source: in-session-2026-07-01.
  Shipped 2026-07-01. Field-level merge on the Duplicates page (merge_preview/merge_apply), atomic via merge_contacts + _write_contact.

- ✅ [CL-0025] **Extend search to cover notes and custom fields.**
  _build_contact_query searches name/email/phone only. Add notes to the LIKE clause and a subquery/EXISTS against custom_fields so a value stored in a custom field is findable.
  **Layman:** Make the search box also look inside notes and custom fields, not just name/email/phone.
  Kind: enhancement.
  Source: in-session-2026-07-01.
  Resolved (2026-07-01): search now covers notes and custom field values via an OR + custom_fields subquery in _build_contact_query. Field values matched, not field names (merge-created "Phone 2"/"Email 2" would otherwise make "phone" match every merged contact). Tests in tests/test_models.py::TestListContacts.

- ✅ [CL-0026] **Support contact photos/avatars.**
  Google People API returns a Google-hosted photo URL per contact. Options: (a) store the remote URL on sync and widen CSP img-src to the Google host, or (b) download to a private dir and serve locally (keeps CSP tight, works offline). Also allow local upload. Design decision -> needs a short spec (cold-eyes) before implementing.
  **Layman:** Show a real photo for each contact like your phone does.
  Kind: feature.
  Source: in-session-2026-07-01.
  Resolved (2026-07-02): local photo storage + Google-sync download + manual upload. Files under PHOTOS_DIR (0700), only ext in DB (contact_photos table); magic-byte validation (JPEG/PNG/GIF/WebP, SVG rejected), 4 MiB cap under the 5 MiB request ceiling; served same-origin so CSP is unchanged. Spec docs/specs/2026-07-01-contact-photos-design.md passed 5-loop /cold-eyes. 228 tests pass (+34).

- ✅ [CL-0033] **Push local contact changes back to Google (two-way sync).**
  Today google_sync.py is import-only (pull). Two-way sync needs: (1) the read-WRITE scope 'https://www.googleapis.com/auth/contacts' instead of the current 'contacts.readonly' in google_auth.py + google_sync.py -> forces a re-consent; (2) People API writes: createContact / updateContact (updatePersonFields + the stored etag for optimistic concurrency) / deleteContact; (3) conflict handling when both sides changed (etag mismatch) -- last-write-wins vs prompt; (4) tracking which local rows are Google-linked (google_id already exists) vs local-only. Non-trivial and touches auth + data integrity -> needs a spec (cold-eyes) before build."
  **Layman:** Right now Google Sync only pulls contacts in. This would also send your edits, new contacts, and deletions back up to Google so both stay in step.
  Kind: feature.
  Source: in-session-2026-07-01.
  Scope refined (2026-07-02): spec docs/specs/2026-07-02-two-way-google-sync.md narrows v2.0 to edits + new contacts (push-create local-only, push-update locally-edited linked contacts) with automatic last-write-wins by Google updateTime timestamp. Deletions are NOT pushed in v2.0 (deferred; a locally-deleted linked contact stays on Google and reappears only on a full re-sync) — supersedes this bullet's original 'deletions' / deleteContact wording. Also folds in an honest 'last edited by you' timestamp (contact_edits table) surfaced on the contact list + footer last-synced. Spec passed /cold-eyes before implementation.
  Resolved (2026-07-02): two-way Google sync shipped as v2.0. Scope upgraded readonly->contacts (single-source SCOPES; legacy-token reconnect via token-file scope probe). sync_contacts is bidirectional (SyncResult): Step-0 snapshot of dirty-linked/local-only sets, pull defers dirty contacts (skip_google_ids), push-create for local-only (persists google_id+etag at once), push-update for edited linked contacts with fresh-etag + index-0 multi-value preservation, timestamp last-write-wins (RFC3339-parsed, tie->Google, absent updateTime->push_no_time+Google-wins), last_synced_at advances unconditionally. No deletions (v2.0). Plus honest edited_at (contact_edits table) surfaced on detail/list/footer. Spec docs/specs/2026-07-02-two-way-google-sync.md passed 4-loop /cold-eyes. 31 tests added; suite 276 green. DESIGN.md §4.4/§6.2/§8.2/§8.3/§9/§13 + README amended.

- ✅ [CL-0037] **Add tags/labels to contacts with filter-by-tag.**
  New tags table + contact_tags join table (many-to-many). UI: tag chips on the contact form and detail page; a tag filter on the contact list (reuse the existing list query filters). Highest-value 'steal' from Monica; fits the SQLite model cleanly with no new dependency.
  **Layman:** Group contacts under labels like 'family', 'work', or 'gym' and filter the list to just one group.
  Kind: feature.
  Source: in-session-2026-07-02 (steal-from-Monica).
  Resolved (2026-07-03): shipped as migration 008_tags.sql + tag model helpers + ?tag= AND filter + detail chips / list filter bar + merge tag-union. Spec docs/specs/2026-07-03-tags-labels-design.md (cold-eyes converged, 9 loops). 31 new tests, 328 suite total green.

- ✅ [CL-0038] **Add an 'upcoming birthdays' view.**
  Birthdays are already captured as a 'birthday' custom field (stored MM-DD or YYYY-MM-DD). Add a view/section that surfaces contacts whose birthday falls in the next N days, month-aware. No schema change needed; query the existing custom_fields rows.
  **Layman:** A little 'birthdays this week/month' list so you never miss one. The birthday data is already stored.
  Kind: feature.
  Source: in-session-2026-07-02 (steal-from-Monica).
  Resolved (2026-07-02): models.upcoming_birthdays() reads existing 'birthday' custom fields (MM-DD or YYYY-MM-DD), month-aware with Feb-29->Feb-28 fallback and age computation; new /contacts/birthdays route + birthdays.html + nav link. 15 tests added, no schema change.

- ✅ [CL-0039] **Add favourite/pinned contacts.**
  Add a boolean 'favourite' column to contacts (idempotent migration note: use a new table or a guarded migration since ADD COLUMN IF NOT EXISTS is unavailable in SQLite — see the CL-0026 pattern). Sort favourites first on the list; a star toggle on detail/list.
  **Layman:** Star the people you contact most so they pin to the top of the list.
  Kind: enhancement.
  Source: in-session-2026-07-02 (steal-from-Monica).
  Resolved (2026-07-03): shipped. Migration 007_favourites.sql (companion table, mirrors 005/006), models.set_favourite/is_favourite + an is_favourite EXISTS scalar pinning favourites first in list_contacts, a CSRF-guarded POST /contacts/<id>/favourite toggle, and star toggles on list rows (HTML5 form= attribute to avoid nesting inside #bulk-form) + the detail header. Spec ran /cold-eyes to convergence (4 loops; a real nested-<form> structural catch in loop 2). 21 new tests; ruff + mypy + 297 tests green.

- 💭 [CL-0040] **Add a per-contact interaction log ('last spoke on ...').**
  New interactions table (contact_id, date, note). Timeline on the contact detail page. NOTE: this nudges the app from 'contact manager' toward 'personal CRM' — kept as considered pending a decision on whether that scope creep is wanted.
  **Layman:** A simple running note of when you last talked to someone and what about.
  Kind: feature.
  Source: in-session-2026-07-02 (steal-from-Monica).

- 💭 [CL-0041] **Link relationships between contacts (spouse-of, works-with).**
  New contact_relationships table (from_id, to_id, kind). Show linked people on the detail page. NOTE: niche; kept as considered until the higher-value tag/birthday features prove the appetite.
  **Layman:** Connect two contacts so you can see family members or colleagues from a contact's page.
  Kind: feature.
  Source: in-session-2026-07-02 (steal-from-Monica).

- 💭 [CL-0042] **Make the web app phone-friendly (responsive + PWA).**
  Lightweight alternative to a native mobile app: responsive CSS for small screens + a web app manifest and a minimal service worker so Android/iOS can install it to the home screen. Kept as considered — only worth doing once the CRM-style features (CL-0037 tags, CL-0038 birthdays, CL-0040 interaction log) land and mobile access to them becomes valuable; the phone's native Contacts app + Google sync already covers plain contact data. No new backend dependency (manifest + JS only). CSP note: a service worker is same-origin so the existing default-src 'self' policy covers it.
  **Layman:** Make the existing website work nicely on a phone screen and let Android 'Add to Home Screen' so it opens like an app — no separate mobile app needed.
  Kind: feature.
  Source: in-session-2026-07-02.

- ✅ [CL-0043] **Show the list "Clear" button for a letter-only (and letter+tag) filter.**
  Pre-existing: the toolbar Clear guard in templates/contacts.html reads
  `{% if search or contact_type %}` — it omits `letter`, so a letter-only
  (alpha-nav) filter shows no Clear affordance. CL-0037 added `or active_tags`
  to it (tags need it) but deliberately left `letter` out to stay in lane. Fix:
  add `or letter` to that guard. The empty-state guard already includes `letter`,
  so the two guards are currently inconsistent. One-line template change + a route
  test asserting Clear shows for `?letter=A`.
  **Layman:** When you filter the contact list by just a starting letter, the "Clear" button is missing, so there's no one-click way back to the full list.
  Kind: fix.
  Source: in-session-2026-07-04 (pre-existing bug surfaced during CL-0037).
  Resolved (2026-07-04): added `or letter` to the toolbar Clear guard in templates/contacts.html:21, making it consistent with the empty-state guard (line 176). Regression test test_clear_button_shown_for_letter_only_filter added to tests/test_routes.py (TestLetterFilter). Full suite 329 passed.

- ✅ [CL-0045] **Fix Google Sync 500: photo helpers committed mid-savepoint, destroying it.**
  Pre-existing bug, explicitly flagged as out-of-scope "code-side
  question" in the two-way-sync spec (§5). models.set_contact_photo /
  clear_contact_photo called db.commit(); the sync pull invokes the first
  from inside the per-contact `SAVEPOINT person`, and a COMMIT destroys
  all SQLite savepoints, so the loop's `RELEASE SAVEPOINT person` threw
  `no such savepoint: person` -> /sync/start 500 on the happy path (any
  pulled contact with a downloadable photo). Fix: both photo helpers no
  longer commit (matching the "caller commits" convention of every other
  models helper); the manual upload route commits in _apply_photo, the
  sync path relies on its existing per-page commit. Regression test wraps
  _upsert_person in a SAVEPOINT and asserts RELEASE survives.
  **Layman:** Google Sync crashed with a "500" whenever a synced contact had a photo. Now it syncs cleanly.
  Kind: fix.
  Source: in-session-2026-07-05 (user-reported /sync/start 500).

## Audit & Review Follow-ups

Items deferred from `/audit` and `/indie-review` sweeps that are not fixed inline.

- ✅ [CL-0008] **Add schema-version tracking and make migrations upgrade-safe.**
  init_db re-runs every .sql file each start (idempotent only because of IF NOT EXISTS); there is no version tracking, so a non-idempotent future migration can't run. Also migration 002's UNIQUE INDEX on custom_fields aborts startup on any pre-existing DB that already holds case-variant duplicate field names. Add a schema_version table and guard/clean before the unique index. No current bug on fresh installs.
  **Layman:** Make future database upgrades safe and repeatable.
  Kind: refactor.
  Source: indie-review-2026-06-30 data-layer.
  Resolved (2026-07-01): schema_version table tracks applied migrations (each runs once); migration 002 dedups case-variant custom-field names before its UNIQUE INDEX.

- ✅ [CL-0009] **Detect an expired Google sync token via HttpError status, not a message substring.**
  google_sync.sync_contacts currently matches 'sync token' in the error text (case-insensitive). Match on googleapiclient.errors.HttpError status 400 + the EXPIRED_SYNC_TOKEN reason so a wording change in Google's message can't break self-healing.
  **Layman:** Make the Google re-sync recovery more reliable.
  Kind: enhancement.
  Source: indie-review-2026-06-30 google-sync.
  Resolved (2026-07-01): expired sync token detected via HttpError 400 + EXPIRED_SYNC_TOKEN reason (_is_expired_sync_token), not a message substring.

- ✅ [CL-0010] **Improve company-vs-individual detection in Google import.**
  _upsert_person flags 'company' only when the organization name exactly equals the display name, so most company contacts import as 'individual'. Use a better signal (presence of an organization with no personal name, contact group membership, etc.).
  **Layman:** Better guess whether an imported Google contact is a person or a company.
  Kind: enhancement.
  Source: indie-review-2026-06-30 google-sync.
  Resolved (2026-07-01): a Google contact with an organization but no given/family name classifies as company.

- ✅ [CL-0011] **Harden the credentials directory permissions to 0700.**
  The token file is created 0600, but ~/.config/contact-list is created with the default umask (often 0755), leaving it traversable by other local users. Create/chmod the dir 0700. Token bytes are already protected; this is defence-in-depth.
  **Layman:** Lock down the folder that holds your Google login token.
  Kind: security.
  Source: indie-review-2026-06-30 google-sync.
  Resolved (2026-07-01): config.ensure_private_dir() makedirs+chmod 0700 at all three creation points.

- ✅ [CL-0012] **Tighten the CSP by removing style-src 'unsafe-inline'.**
  Current CSP (matching DESIGN) allows inline style attributes. Move the handful of inline style= attributes (base.html, contacts.html, duplicates.html) into the stylesheet, then drop 'unsafe-inline' from style-src.
  **Layman:** Make the page's security policy a little stricter.
  Kind: security.
  Source: indie-review-2026-06-30 routes.
  Resolved (2026-07-01): inline style= moved to CSS utility classes; style-src 'unsafe-inline' dropped from the CSP; DESIGN.md §6.3 updated.

- ✅ [CL-0013] **Normalize phone numbers in duplicate detection.**
  find_duplicates matches phone with exact string equality, so '+1 555-1234' and '5551234' aren't flagged as the same. Compare on a normalized (E.164) form. Mitigated today because input is normalized via format_phone, but imported/legacy data can differ.
  **Layman:** Catch duplicate contacts even when the same number is typed differently.
  Kind: enhancement.
  Source: indie-review-2026-06-30 data-layer.
  Resolved (2026-07-01): find_duplicates compares phones on normalized E.164 (phoneutil.normalize_e164), region from settings, exact-match fallback.

- ✅ [CL-0014] **Fold accented initials onto their base letter in the alpha nav.**
  Non-ASCII initials are now consistently bucketed under '#' (count and filter agree). A nicer UX would fold 'É'->'E' (unicodedata) so accented-initial names appear under their base letter. Requires consistent folding in both get_letter_counts and the letter filter.
  **Layman:** Show names like 'Élodie' under 'E' instead of the '#' bucket.
  Kind: enhancement.
  Source: indie-review-2026-06-30 data-layer.
  Resolved (2026-07-01): first_letter() SQLite function folds accented initials to the base letter, used by both the counts and the letter filter.

- ✅ [CL-0015] **Add a data-layer contact_type guard (defense-in-depth).**
  create_contact relies on the SQL CHECK(type IN ('individual','company')) constraint; the route validates too. Add an explicit guard in the data layer for a clean error instead of a raw IntegrityError 500, mirroring the field_name validation now in place.
  **Layman:** Extra safety check so an invalid contact type fails cleanly.
  Kind: enhancement.
  Source: indie-review-2026-06-30 data-layer.
  Resolved (2026-07-01): create/update_contact raise ValueError on a bad contact_type instead of a raw IntegrityError 500.

- ✅ [CL-0019] **Make Google-sync per-record isolation robust on Python 3.10/3.11.**
  The per-contact SAVEPOINT/ROLLBACK isolation in google_sync.sync_contacts is verified correct on Python 3.12+ (this system runs 3.13). On legacy sqlite3 (Python <=3.11, isolation_level='') a SAVEPOINT issued in autocommit can make ROLLBACK TO SAVEPOINT a no-op, silently weakening the isolation. DESIGN.md targets Python 3.10+. Either require 3.12+ (note in DESIGN/requirements) or add an explicit BEGIN / sys.version_info guard.
  **Layman:** Make sure the import safety net works on older Python versions too.
  Kind: fix.
  Source: indie-review-2026-06-30 loop3.
  Resolved (2026-07-01): documented Python 3.12+ requirement for the SAVEPOINT isolation (DESIGN.md §3 + requirements.txt) and flagged it at the SAVEPOINT.

- ✅ [CL-0020] **Make a mid-pagination Google-sync error preserve already-imported pages.**
  A non-token exception from people().list() mid-pagination returns (0, error) and the whole transaction rolls back, discarding successfully-imported earlier pages and reporting 0 synced. Since import is idempotent on google_id, commit completed pages (or persist a resume cursor) so a transient API hiccup on page 2 doesn't throw away page 1.
  **Layman:** If a sync fails halfway, keep the contacts already imported instead of discarding them.
  Kind: enhancement.
  Source: indie-review-2026-06-30 loop3.
  Resolved (2026-07-01): sync commits each page and returns the count synced so far, so a mid-pagination error keeps earlier imports (guarded reset).

- ✅ [CL-0021] **Bind the dev server to 127.0.0.1 literally instead of 'localhost'.**
  app.py uses app.run(host='localhost'); DESIGN.md §6.3 specifies 127.0.0.1. 'localhost' can resolve to ::1 or, under an unusual /etc/hosts, a broader interface. Use the literal 127.0.0.1 to match the contract. Only affects the built-in dev server, not a gunicorn/uwsgi deployment.
  **Layman:** Tiny networking nitpick so the app matches its stated localhost-only rule exactly.
  Kind: security.
  Source: indie-review-2026-06-30 loop3.
  Resolved (2026-07-01): dev server binds literal 127.0.0.1 instead of 'localhost'.

- ✅ [CL-0027] **Normalize phone numbers on the duplicates scan page.**
  find_all_duplicates() groups phones by exact string match, while find_duplicates() normalizes to E.164 (CL-0013). So the scan page and the on-create warning disagree. Group by phoneutil.normalize_e164(phone, region) so both use the same comparison.
  **Layman:** The duplicates page misses phone numbers that are the same but typed differently — make it catch them like the add-contact warning already does.
  Kind: fix.
  Source: in-session-2026-07-01.
  Resolved (2026-07-01): find_all_duplicates now buckets phones by phoneutil.normalize_e164(phone, region); route passes g.settings['phone_region']. New test test_duplicate_phones_normalized. Scan page now agrees with the on-create warning.

- ✅ [CL-0028] **Set SESSION_COOKIE_SAMESITE = 'Lax'.**
  Not set in config.py (Flask defaults it to None). Defense-in-depth under the existing CSRF token; no downside on a same-origin localhost app. One line in Config.
  **Layman:** Add a second, browser-enforced guard against cross-site form submissions.
  Kind: security.
  Source: in-session-2026-07-01.
  Resolved (2026-07-01): Config.SESSION_COOKIE_SAMESITE = 'Lax'. Verified SameSite=Lax on the session Set-Cookie.

- ✅ [CL-0029] **Add a GitHub Actions CI workflow.**
  No .github/workflows/ exists. Add a workflow running ruff + mypy + pytest on Python 3.12 and 3.13. Public repo -> free Linux runner minutes; guards the 123-test suite on every push.
  **Layman:** Automatically run the tests and checks every time code is pushed.
  Kind: chore.
  Source: in-session-2026-07-01.
  Resolved (2026-07-01): added .github/workflows/ci.yml — ruff + mypy + pytest matrix on Python 3.12 and 3.13, runs on push and PR to main. Least-privilege permissions (contents: read), pip cache, actions/checkout@v7 + setup-python@v6.

- ✅ [CL-0030] **Add a pyproject.toml for tool configuration.**
  Tool config (ruff line-length 100, mypy strictness, pytest paths) is implicit/local-cache-only today. Codify it so CI and local runs share identical settings.
  **Layman:** Put the code-style and test settings in one file so they're the same everywhere.
  Kind: chore.
  Source: in-session-2026-07-01.
  Resolved (2026-07-01): added pyproject.toml centralising ruff (line-length 100, target py312), mypy (py312, scoped stub-ignores for the untyped Google client libs), and pytest (testpaths=tests) config. Verified ruff/mypy/pytest all read config from the file and pass (124 tests green). One latent type bug fixed en route: models.create_contact narrows cursor.lastrowid (int|None) with an assert.

- 📋 [CL-0044] **Re-baseline or retire DESIGN.md §14 "Total pip install < 20 MB" budget row.**
  DESIGN.md §14's `Total pip install | < 20 MB` row is stale by ~15x: the
  current venv site-packages is ~296 MB (googleapiclient ~100 MB, phonenumbers
  ~46 MB, plus grpc/others), independent of CL-0035. CL-0035 adds Pillow 12.3.0 (~21 MB:
  PIL 7 MB + pillow.libs 14 MB). The row reads as a live gate but is
  aspirational only. Either raise it to a realistic figure (or split "wheel size"
  vs "installed size"), or drop the row and keep only the meaningful shipped-`.py`
  soft target. Pre-existing; not introduced by CL-0035.
  **Layman:** One line in the design doc says the installed code should be under 20 MB, but it's already about 296 MB — the line is long out of date and misleading.
  Kind: doc-fix.
  Source: in-session-2026-07-04 (surfaced during CL-0035 cold-eyes).

## Efficiency & Refactoring

Performance and code-health opportunities surfaced during the 2026-06-30 review.
None are urgent — the app already meets the DESIGN.md efficiency targets — but
they reduce duplication and query count.

- ✅ [CL-0016] **Extract a shared phone-format/region helper.**
  _format_phone is duplicated in routes/contacts.py (format_phone) and google_sync.py (_format_phone) with the same DEFAULT_REGION='ZA'. Extract one helper (e.g. a phoneutil module) and call it from both; ties in with making the region a user setting (CL-0006).
  **Layman:** Remove duplicated phone-number code so there's one place to maintain it.
  Kind: refactor.
  Source: in-session-2026-06-30 suggested.
  Resolved (2026-07-01): shared phoneutil.format_phone(raw, region) extracted; duplication in routes/contacts.py and google_sync.py removed.

- ✅ [CL-0017] **Consolidate the contact-list page's aggregate queries.**
  contact_list runs count_contacts + list_contacts (which also counts) + get_letter_counts + a type-breakdown query on every load. list_contacts already returns a total that the route discards (recomputes via count_contacts). Reuse it, and fold the type breakdown into fewer round-trips. Minor — SQLite is fast for one user.
  **Layman:** Make the main list page do a little less database work per load.
  Kind: perf.
  Source: in-session-2026-06-30 suggested.
  Resolved (2026-07-01): contact_list now reuses the total from list_contacts (page-clamp folded into list_contacts) instead of a separate count_contacts call, and the type breakdown moved into a get_type_counts model helper — 5 aggregate queries down to 4 per list load. Letter/type counts left as separate readable queries (UNION micro-opt not worth it on a single-user localhost DB). 101 tests green.

- ✅ [CL-0018] **Extract a custom-field-name validation helper.**
  The field_name validation loop is now duplicated at the top of create_contact and update_contact in models.py. Extract a small _validate_field_names(custom_fields) helper once a third call-site appears (Rule of Three); noted now so it isn't forgotten.
  **Layman:** Tidy a small bit of repeated validation code.
  Kind: refactor.
  Source: in-session-2026-06-30 suggested.
  Resolved (2026-06-30): extracted _validate_custom_field_names() in models.py during the audit fix-pass; it validates format and rejects case-insensitive duplicates, called by both create_contact and update_contact.

- ✅ [CL-0031] **Avoid the per-request COUNT(*) for the nav badge.**
  _inject_globals runs SELECT COUNT(*) FROM contacts on every request, including error pages. The contact-list route already computes total; compute the badge count only where it is shown, or cache it per request.
  **Layman:** Stop recounting every contact on every page load just to fill in the little number badge.
  Kind: perf.
  Source: in-session-2026-07-01.
  Resolved (2026-07-01): nav-badge count cached on g via contact_count(); unfiltered list route pre-seeds g.contact_count = total, so the list page no longer issues a second COUNT(*). Badge still shows the full count on filtered pages.

- 📋 [CL-0032] **Consider SQLite FTS5 for full-text search if the contact count grows large.**
  Search uses LIKE '%term%' (leading wildcard), which cannot use any index and always full-scans; the idx_contacts_email/phone indexes only help exact-match/dedup paths, not substring search. At the current single-user scale (~330 rows) this is sub-millisecond, so this is deferred. If N reaches the thousands, add an FTS5 virtual table (contentless, synced via triggers) over name/email/phone/notes/custom_fields. Pairs with CL-0025 (search notes + custom fields). NOTE: WAL mode, synchronous=NORMAL, 8MB cache, temp_store=MEMORY, busy_timeout, and indexes on all filter/sort/join columns are already in place (db.py + migrations) — the DB is otherwise well-tuned.
  **Layman:** If the address book ever grows to many thousands of contacts, switch the search to a proper text index so it stays instant.
  Kind: perf.
  Source: in-session-2026-07-01.
  Promoted considered->planned (2026-07-02): though the maintainer's own contact count is small, other users may have thousands of contacts where the current LIKE-based search degrades. Worth implementing for general users. FTS5 is bundled with SQLite (no new dependency).

- ✅ [CL-0034] **Add cache headers to the contact-photo route so browsers cache avatars.**
  send_from_directory in routes/contacts.py photo() sets no max_age, so browsers revalidate each avatar on every navigation. Pass max_age (e.g. 1 day) and rely on the existing ETag/Last-Modified for conditional revalidation. Small, self-contained perf win on photo-heavy list pages.
  **Layman:** Right now the browser re-downloads every contact photo on each page. Telling it to keep photos cached makes list pages load instantly after the first visit.
  Kind: perf.
  Source: in-session-2026-07-02.
  Resolved (2026-07-02): photo() passes max_age=86400 to send_from_directory; ETag/Last-Modified still enable conditional revalidation. Test test_photo_response_is_cacheable asserts max-age=86400.

- ✅ [CL-0035] **Generate downscaled photo thumbnails instead of serving full-size uploads.**
  List/detail avatars display at ~40-96px but the full upload is served. Generate a thumbnail (e.g. 128px) on save and serve that for list/detail; keep the original for download. User has lifted the no-C-extension dependency ban for this: Pillow may be added. NOTE: requires updating DESIGN.md §3 dependency budget (currently bans non-stdlib C-extension deps and caps at <8 direct pip packages) and CLAUDE.md convention. Spec/cold-eyes before implementing.
  **Layman:** A 4 MB photo is currently sent in full even though it shows as a tiny circle. Making small thumbnail copies means the list page sends kilobytes, not megabytes.
  Kind: perf.
  Source: in-session-2026-07-02.
  Resolved (2026-07-04): 256 px thumbnails via Pillow 12.3.0. Spec docs/specs/2026-07-04-photo-thumbnails-design.md passed /cold-eyes to convergence (10 loops; loop 8 caught a track-latest violation — pinned >=12.0,<13.0). photos.generate_thumbnail + _write_thumbnail (eager on save, atomic write) + avatar_filename (lazy self-heal + full-size fallback); serve route serves the thumbnail. Original kept on disk. DESIGN.md §3 (Pillow authorised, 7 runtime deps), §6 File-uploads row, and the 2026-07-01 spec updated. 21 new tests; 345 total green; ruff+mypy clean. Filed CL-0044 for the pre-existing stale §14 pip-install budget.

- ✅ [CL-0036] **Split routes/contacts.py (696 lines) into contacts + import/export + merge modules.**
  routes/contacts.py exceeds the DESIGN §14 file-size cap. Extract CSV/vCard import+export routes and the merge_preview/merge_apply routes into their own blueprints/modules. Pure structural refactor; the test suite (229 tests) locks behaviour.
  **Layman:** One file currently handles contacts, CSV/vCard import-export, and merging all at once. Splitting it into focused files makes each part easier to find and change. No behaviour change.
  Kind: refactor.
  Source: in-session-2026-07-02.
  Resolved (2026-07-03): split into routes/contacts.py (core CRUD + list/detail/photo), routes/import_export.py (CSV+vCard import/export), and routes/merge.py — all attached to the same 'contacts' blueprint, so every endpoint name and URL is unchanged. 276 tests + ruff + mypy all green (zero behaviour change). Correction: the "exceeds the §14 file-size cap" premise was inaccurate — §14 is a ~100 KB *total* soft budget across shipped .py, not a per-file cap (contacts.py was ~24 KB / 716 lines), so this was a readability split, not a cap violation.

## Shipped
