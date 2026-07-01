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

## Audit & Review Follow-ups

Items deferred from `/audit` and `/indie-review` sweeps that are not fixed inline.

- 📋 [CL-0008] **Add schema-version tracking and make migrations upgrade-safe.**
  init_db re-runs every .sql file each start (idempotent only because of IF NOT EXISTS); there is no version tracking, so a non-idempotent future migration can't run. Also migration 002's UNIQUE INDEX on custom_fields aborts startup on any pre-existing DB that already holds case-variant duplicate field names. Add a schema_version table and guard/clean before the unique index. No current bug on fresh installs.
  **Layman:** Make future database upgrades safe and repeatable.
  Kind: refactor.
  Source: indie-review-2026-06-30 data-layer.

- 📋 [CL-0009] **Detect an expired Google sync token via HttpError status, not a message substring.**
  google_sync.sync_contacts currently matches 'sync token' in the error text (case-insensitive). Match on googleapiclient.errors.HttpError status 400 + the EXPIRED_SYNC_TOKEN reason so a wording change in Google's message can't break self-healing.
  **Layman:** Make the Google re-sync recovery more reliable.
  Kind: enhancement.
  Source: indie-review-2026-06-30 google-sync.

- 📋 [CL-0010] **Improve company-vs-individual detection in Google import.**
  _upsert_person flags 'company' only when the organization name exactly equals the display name, so most company contacts import as 'individual'. Use a better signal (presence of an organization with no personal name, contact group membership, etc.).
  **Layman:** Better guess whether an imported Google contact is a person or a company.
  Kind: enhancement.
  Source: indie-review-2026-06-30 google-sync.

- 📋 [CL-0011] **Harden the credentials directory permissions to 0700.**
  The token file is created 0600, but ~/.config/contact-list is created with the default umask (often 0755), leaving it traversable by other local users. Create/chmod the dir 0700. Token bytes are already protected; this is defence-in-depth.
  **Layman:** Lock down the folder that holds your Google login token.
  Kind: security.
  Source: indie-review-2026-06-30 google-sync.

- 📋 [CL-0012] **Tighten the CSP by removing style-src 'unsafe-inline'.**
  Current CSP (matching DESIGN) allows inline style attributes. Move the handful of inline style= attributes (base.html, contacts.html, duplicates.html) into the stylesheet, then drop 'unsafe-inline' from style-src.
  **Layman:** Make the page's security policy a little stricter.
  Kind: security.
  Source: indie-review-2026-06-30 routes.

- 📋 [CL-0013] **Normalize phone numbers in duplicate detection.**
  find_duplicates matches phone with exact string equality, so '+1 555-1234' and '5551234' aren't flagged as the same. Compare on a normalized (E.164) form. Mitigated today because input is normalized via format_phone, but imported/legacy data can differ.
  **Layman:** Catch duplicate contacts even when the same number is typed differently.
  Kind: enhancement.
  Source: indie-review-2026-06-30 data-layer.

- 📋 [CL-0014] **Fold accented initials onto their base letter in the alpha nav.**
  Non-ASCII initials are now consistently bucketed under '#' (count and filter agree). A nicer UX would fold 'É'->'E' (unicodedata) so accented-initial names appear under their base letter. Requires consistent folding in both get_letter_counts and the letter filter.
  **Layman:** Show names like 'Élodie' under 'E' instead of the '#' bucket.
  Kind: enhancement.
  Source: indie-review-2026-06-30 data-layer.

- 📋 [CL-0015] **Add a data-layer contact_type guard (defense-in-depth).**
  create_contact relies on the SQL CHECK(type IN ('individual','company')) constraint; the route validates too. Add an explicit guard in the data layer for a clean error instead of a raw IntegrityError 500, mirroring the field_name validation now in place.
  **Layman:** Extra safety check so an invalid contact type fails cleanly.
  Kind: enhancement.
  Source: indie-review-2026-06-30 data-layer.

- 📋 [CL-0019] **Make Google-sync per-record isolation robust on Python 3.10/3.11.**
  The per-contact SAVEPOINT/ROLLBACK isolation in google_sync.sync_contacts is verified correct on Python 3.12+ (this system runs 3.13). On legacy sqlite3 (Python <=3.11, isolation_level='') a SAVEPOINT issued in autocommit can make ROLLBACK TO SAVEPOINT a no-op, silently weakening the isolation. DESIGN.md targets Python 3.10+. Either require 3.12+ (note in DESIGN/requirements) or add an explicit BEGIN / sys.version_info guard.
  **Layman:** Make sure the import safety net works on older Python versions too.
  Kind: fix.
  Source: indie-review-2026-06-30 loop3.

- 📋 [CL-0020] **Make a mid-pagination Google-sync error preserve already-imported pages.**
  A non-token exception from people().list() mid-pagination returns (0, error) and the whole transaction rolls back, discarding successfully-imported earlier pages and reporting 0 synced. Since import is idempotent on google_id, commit completed pages (or persist a resume cursor) so a transient API hiccup on page 2 doesn't throw away page 1.
  **Layman:** If a sync fails halfway, keep the contacts already imported instead of discarding them.
  Kind: enhancement.
  Source: indie-review-2026-06-30 loop3.

- 📋 [CL-0021] **Bind the dev server to 127.0.0.1 literally instead of 'localhost'.**
  app.py uses app.run(host='localhost'); DESIGN.md §6.3 specifies 127.0.0.1. 'localhost' can resolve to ::1 or, under an unusual /etc/hosts, a broader interface. Use the literal 127.0.0.1 to match the contract. Only affects the built-in dev server, not a gunicorn/uwsgi deployment.
  **Layman:** Tiny networking nitpick so the app matches its stated localhost-only rule exactly.
  Kind: security.
  Source: indie-review-2026-06-30 loop3.

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

## Shipped
