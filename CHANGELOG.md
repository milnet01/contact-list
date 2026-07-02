# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- ****Upcoming Birthdays view** — a new page listing contacts whose birthday falls within the next N days (default 30, `?days=` to widen), month-aware with leap-day handling and the age they'll turn.** (CL-0038)

- **Contact photos/avatars (CL-0026)**
  Contacts can now have a real photo instead of the coloured initial. Photos are pulled from Google on sync (real photos only, not the grey placeholder) and can be uploaded by hand on the Add/Edit page. They're stored privately on your machine and served by the app itself, so the strict security policy is unchanged and photos work offline. Uploads are checked to be genuine JPEG/PNG/GIF/WebP images under 4 MB.

- **Search now covers notes and custom field values, not just name/email/phone (CL-0025)**
  The contact search box now also looks inside each contact's notes and
  custom field values, so a word that only appears in a note or a custom
  field will still find the contact. Field values are matched, not field
  names, so merge-created fields like "Phone 2" don't cause spurious hits.

- **Merge action on the Duplicates page** (CL-0024)
  Select two or more contacts, choose the winning value per field, and
  combine them into one with no data lost.

- **vCard (.vcf) import and export** (CL-0023)
  Reads vCard 3.0/4.0 files and exports all contacts as one .vcf. Custom
  fields round-trip losslessly; no new dependency (hand-rolled parser).

- **CSV import with a column-mapping screen that remembers your choices** (CL-0022)
  Upload a CSV, match its columns to contact fields (auto-guessed and
  remembered per header layout), and import. Existing contacts are filled
  in additively — blank fields only, never overwritten; extra emails/phones
  become custom fields.

- **Continuous-integration workflow and shared tool configuration.**
  A GitHub Actions workflow runs ruff, mypy, and the full test suite on
  Python 3.12 and 3.13 for every push and pull request, so regressions are
  caught automatically. A new pyproject.toml centralises the linter,
  type-checker, and pytest settings so local and CI runs use identical
  configuration. (CL-0029, CL-0030)

- **Settings page for per-user preferences**
  A new /settings page lets you customise the app and have it remembered
  server-side (in the database) across devices: timezone and date format for
  how timestamps display, theme (light/dark/colour schemes, now applied without
  a flash), layout (compact/roomy and list/card views), default phone region,
  contacts-per-page, default sort column/direction, and the default type for new
  contacts. Phone formatting was unified into a single shared helper that uses
  your chosen region (CL-0001 through CL-0007, CL-0016).

- **Project docs and tooling: README, ROADMAP, CHANGELOG, a project-level CLAUDE.md, an MIT LICENSE, and an Ants .ants/project.json layout declaration.**

### Changed

- ****Contact photos are now browser-cacheable** — the avatar route sends a one-day `Cache-Control` max-age (ETag/Last-Modified still allow revalidation), so list pages no longer re-download every photo on each navigation.** (CL-0034)

- **Cache the nav-badge contact count per request; the unfiltered contact-list page no longer runs a second `COUNT(*)`.** (CL-0031)

- **Card view now uses masonry packing (CSS multi-column) with a two-tone alternation so adjacent cards are easier to tell apart.**

- **Card view now flows multiple contacts per row as a responsive grid, instead of one full-width card per row.**

- **Settings page polish: section headings no longer punch through the fieldset border (rendered as full-width header + divider), fields stack one per row, and number inputs pick up the shared full-width input styling.**

- **Version-tracked, upgrade-safe database migrations**
  Migrations are recorded and run exactly once, and the custom-field uniqueness migration cleans pre-existing duplicates before applying so it can't abort startup on an older database. Invalid contact types now fail with a clear error. Requires Python 3.12+. CL-0008, CL-0015, CL-0019.

- **Smarter duplicate detection and alphabetical navigation**
  Duplicate detection matches phone numbers regardless of how they're formatted, and the A-Z navigation folds accented initials onto their base letter (e.g. Élodie under E). CL-0013, CL-0014.

- **More reliable Google Contacts sync**
  Expired sync tokens are detected by error status rather than message text; contacts with an organization and no personal name import as companies; and if a sync fails partway, the contacts already imported are kept instead of discarded. CL-0009, CL-0010, CL-0020.

- **Contact-list page does one fewer database query per load**
  The main list page reused the row total it already had instead of counting
  the same rows twice, and its contact-type tally moved into the data layer
  alongside the other lookups. Same output, a little less work per page load
  (CL-0017).

- **Bump phonenumbers pin to >=9.0,<10.0 to match the current major**
  The declared pin (>=8.13,<9.0) lagged the installed/current major
  (9.0.26). The API the app uses (parse, format_number, is_valid_number,
  NumberParseException, SUPPORTED_REGIONS) is stable across 8.x->9.x, so no
  caller changes were needed; the full test suite (67 tests) passes on 9.0.26.
  Updated requirements.txt and the DESIGN.md dependency block in lockstep.

- **Tests use pytest tmp_path for all filesystem paths instead of hardcoded /tmp directories.**

- **Enforce custom-field-name validation (format and case-insensitive duplicates) in the data layer, not only in the route.**

### Removed

- **Removed the unused count_contacts() model helper; every caller uses list_contacts's returned total (CL-0017).**

### Fixed

- **Duplicates scan page now normalizes phone numbers to E.164 before comparing, so the same number typed differently is caught — matching the add-contact warning.** (CL-0027)

- **Recently-viewed widget builds DOM nodes via createElement/textContent instead of innerHTML, removing an XSS surface from contact names.**

- **Alpha index: bucket non-ASCII initials consistently so a letter's count always matches its filtered results.**

- **Data layer: wrap contact create/update/delete in a transaction so a failed write rolls back cleanly instead of leaving a half-applied change for the next commit to flush.**

- **Google sync: count only contacts actually imported (deletes and no-name records no longer inflate the total); store only complete birthdays instead of fabricating Jan 1 or a '????' year.**

- **Google sync: reset pagination state on an expired-sync-token retry, and never overwrite a captured sync token with None on a later page.**

- **Google sync: isolate each contact in its own SAVEPOINT so one malformed record no longer aborts or rolls back the whole import.**

### Security

- **Set `SESSION_COOKIE_SAMESITE = 'Lax'` as browser-enforced defence-in-depth on top of the CSRF token.** (CL-0028)

- **Tightened local security hardening**
  Locked the Google-credentials folder to 0700, bound the dev server to the literal 127.0.0.1, and removed 'unsafe-inline' from the page security policy's style-src (inline styles moved into the stylesheet). CL-0011, CL-0021, CL-0012.

- **Stop surfacing raw Google API error text to the user on sync failure; log it server-side and show a generic message.**

- **Create the Google OAuth token file with 0600 permissions atomically, closing the brief world-readable window between write and chmod.**

- **Harden redirect-target validation against the `/\` backslash and control-character open-redirect/header-splitting variants.**

- **Persist the Flask secret key under the config dir so signed sessions and CSRF tokens survive restarts and multiple workers (was regenerated per process).**

## [1.0.0] - 2026-06-30

### Added
- Initial public release of Contact List — a lightweight, self-hosted Flask
  contact manager with SQLite storage.
- Contact CRUD for individuals and companies with name, email, phone, and notes.
- User-defined custom fields per contact (EAV model, no schema changes needed).
- Search, type/letter filtering, sorting, and pagination on the contact list.
- Duplicate detection and review.
- CSV export of all contacts.
- One-way (read-only) Google Contacts import via the Google People API.
- Security hardening: parameterized SQL, CSRF tokens on state-changing forms,
  Jinja2 autoescaping, and a strict Content-Security-Policy. Binds to localhost.
