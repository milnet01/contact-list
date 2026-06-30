# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- **Bump phonenumbers pin to >=9.0,<10.0 to match the current major**
  The declared pin (>=8.13,<9.0) lagged the installed/current major
  (9.0.26). The API the app uses (parse, format_number, is_valid_number,
  NumberParseException, SUPPORTED_REGIONS) is stable across 8.x->9.x, so no
  caller changes were needed; the full test suite (67 tests) passes on 9.0.26.
  Updated requirements.txt and the DESIGN.md dependency block in lockstep.

- **Tests use pytest tmp_path for all filesystem paths instead of hardcoded /tmp directories.**

- **Enforce custom-field-name validation (format and case-insensitive duplicates) in the data layer, not only in the route.**

### Fixed

- **Recently-viewed widget builds DOM nodes via createElement/textContent instead of innerHTML, removing an XSS surface from contact names.**

- **Alpha index: bucket non-ASCII initials consistently so a letter's count always matches its filtered results.**

- **Data layer: wrap contact create/update/delete in a transaction so a failed write rolls back cleanly instead of leaving a half-applied change for the next commit to flush.**

- **Google sync: count only contacts actually imported (deletes and no-name records no longer inflate the total); store only complete birthdays instead of fabricating Jan 1 or a '????' year.**

- **Google sync: reset pagination state on an expired-sync-token retry, and never overwrite a captured sync token with None on a later page.**

- **Google sync: isolate each contact in its own SAVEPOINT so one malformed record no longer aborts or rolls back the whole import.**

### Security

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
