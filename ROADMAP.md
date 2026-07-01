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

- 📋 [CL-0022] **Import contacts from a CSV file.**
  Mirror the existing CSV export. Map Name/Type/Email/Phone/Notes columns and reuse create_contact + _validate_form + find_duplicates so imported rows get the same validation and duplicate warnings as manual entry.
  **Layman:** Let the user bring contacts in from a spreadsheet, not just export them.
  Kind: feature.
  Source: in-session-2026-07-01.

- 📋 [CL-0023] **Support vCard (.vcf) import and export.**
  Add a .vcf export alongside export_contacts, and a .vcf import path. vCard is the universal interchange format for phones/Apple Contacts/Thunderbird.
  **Layman:** Read and write the standard contact-card format that phones and mail apps use.
  Kind: feature.
  Source: in-session-2026-07-01.

- 📋 [CL-0024] **Add a merge action to the duplicates page.**
  The duplicates page is read-only today. Add a merge: keep one contact, fold in the other's non-empty fields + custom_fields, then delete the loser. Wrap in a transaction.
  **Layman:** Let the user combine two duplicate contacts into one from the duplicates screen.
  Kind: feature.
  Source: in-session-2026-07-01.

- 📋 [CL-0025] **Extend search to cover notes and custom fields.**
  _build_contact_query searches name/email/phone only. Add notes to the LIKE clause and a subquery/EXISTS against custom_fields so a value stored in a custom field is findable.
  **Layman:** Make the search box also look inside notes and custom fields, not just name/email/phone.
  Kind: enhancement.
  Source: in-session-2026-07-01.

- 📋 [CL-0026] **Support contact photos/avatars.**
  Google People API returns a Google-hosted photo URL per contact. Options: (a) store the remote URL on sync and widen CSP img-src to the Google host, or (b) download to a private dir and serve locally (keeps CSP tight, works offline). Also allow local upload. Design decision -> needs a short spec (cold-eyes) before implementing.
  **Layman:** Show a real photo for each contact like your phone does.
  Kind: feature.
  Source: in-session-2026-07-01.

- 📋 [CL-0033] **Push local contact changes back to Google (two-way sync).**
  Today google_sync.py is import-only (pull). Two-way sync needs: (1) the read-WRITE scope 'https://www.googleapis.com/auth/contacts' instead of the current 'contacts.readonly' in google_auth.py + google_sync.py -> forces a re-consent; (2) People API writes: createContact / updateContact (updatePersonFields + the stored etag for optimistic concurrency) / deleteContact; (3) conflict handling when both sides changed (etag mismatch) -- last-write-wins vs prompt; (4) tracking which local rows are Google-linked (google_id already exists) vs local-only. Non-trivial and touches auth + data integrity -> needs a spec (cold-eyes) before build."
  **Layman:** Right now Google Sync only pulls contacts in. This would also send your edits, new contacts, and deletions back up to Google so both stay in step.
  Kind: feature.
  Source: in-session-2026-07-01.

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

- 💭 [CL-0032] **Consider SQLite FTS5 for full-text search if the contact count grows large.**
  Search uses LIKE '%term%' (leading wildcard), which cannot use any index and always full-scans; the idx_contacts_email/phone indexes only help exact-match/dedup paths, not substring search. At the current single-user scale (~330 rows) this is sub-millisecond, so this is deferred. If N reaches the thousands, add an FTS5 virtual table (contentless, synced via triggers) over name/email/phone/notes/custom_fields. Pairs with CL-0025 (search notes + custom fields). NOTE: WAL mode, synchronous=NORMAL, 8MB cache, temp_store=MEMORY, busy_timeout, and indexes on all filter/sort/join columns are already in place (db.py + migrations) — the DB is otherwise well-tuned.
  **Layman:** If the address book ever grows to many thousands of contacts, switch the search to a proper text index so it stays instant.
  Kind: perf.
  Source: in-session-2026-07-01.

## Shipped
