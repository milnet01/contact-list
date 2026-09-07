# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`LWSM_MANAGED=1` runs without the system-tray icon** (CL-0056)
  Headless, logging to stdout as normal. A presentation hint only — it
  affects nothing but whether the icon appears.

- **`PORT` environment variable for an external process manager** (CL-0056)
  Precedence is `PORT` → `CONTACT_LIST_PORT` → 5002. `PORT` must be an
  integer in 1024–65535; an invalid value is a startup error naming the
  value and a non-zero exit, never a silent fall back to another port.
  Unset or empty means "not supplied" and changes nothing. Every path
  that binds now prints `Listening on http://127.0.0.1:<port>` to stdout.

### Changed

- **Starting the app no longer opens a browser tab; the tray icon is the way in** (CL-0060)
  A start whose tray icon appears now opens nothing. Two cases still open the page: launching a second copy while one is already running, and a start where the tray could not appear at all (a desktop with no system tray) — without that fallback the app would be running with no icon, no tab and no visible address.

- **A busy port that `PORT` named explicitly is now a failure, not a hand-off** (CL-0056)
  When `PORT` names a port and something already holds it, the launcher
  exits non-zero and opens no browser instead of handing off to the
  existing instance. Without `PORT` the hand-off is unchanged.

### Fixed

- **Google Sync works in the downloadable app** (CL-0080)
  Opening the Google Sync page in a packaged build showed an error page
  instead of the page. A library the sync code needs was never included in
  the bundle, so the feature could not work there at all — while running
  from source was unaffected, which is why no test caught it. Found by
  launching a real build and opening the page.

- **Imported files can no longer store oversized contact fields** (CL-0068)
  Name, email, phone, notes and custom-field values are now length-checked
  where the data is written rather than only in the browser, so an imported
  CSV or vCard gets the same limits the contact form shows. The
  fifty-custom-field limit applies to imports too; it previously applied
  only to the form.

- **Replacing a contact photo no longer risks losing the old one** (CL-0071)
  The previous photo was deleted before the new one was written, so a
  failure in between left the contact with no photo at all and a broken
  avatar. The new photo is now put in place first.

- **Two copies of the app starting at once agree on one session key** (CL-0069)
  On a first run they could each generate a different key, and the loser
  rejected every form submission. An unreadable key file also stopped the
  app starting with no message anywhere; it now logs and creates a new one.

- **A photo that cannot be saved no longer looks like the contact failed to save** (CL-0079)
  A full disk raised an error page after the contact had already been
  stored, so the user could not tell it had worked. It now says the contact
  was saved and the photo was not.

- **Back-to-top and the sticky filter bar work on every page** (CL-0048)
  Both were stranded behind an early return that fires on every page
  except the contact form, so the button never appeared where it was
  useful and the filter bar fell back to a fixed offset. The scroll to top
  now also respects a reduced-motion preference.

- **The system-tray icon now appears on Windows and macOS**
  The appindicator backend was pinned on every platform, not just Linux.
  pystray imports the named backend unconditionally and does not fall back,
  and that backend needs a Linux-only library — so the tray failed to start
  on Windows and macOS, and the app then opened a browser tab on every
  launch as its no-tray fallback. Both platforms now select their own
  native backend, as the design document always said they would.

- **Multi-line notes survive a vCard export and re-import**
  Notes typed on more than one line were exported with a raw carriage
  return, which acted as an end-of-line marker when the file was read back
  — so everything after the first line was lost. This also closes a way for
  imported contact data to inject extra entries into an exported file.

- **Emails and phone numbers with custom labels now import from Google and Apple exports**
  Both write those entries with a group prefix on the property name, which
  the parser did not recognise, so exactly the labelled emails and phone
  numbers were dropped without a word.

- **A vCard import that skips contacts now says so**
  Contacts the importer refused were counted as neither imported nor
  skipped, so a file where most records failed still reported an
  unqualified success. The summary now reports the skipped count and the
  reason for each, as the CSV import already did.

- **Dates and the timezone setting work in the Windows build**
  Windows ships no system timezone database, so the frozen build had none:
  the Settings timezone list rendered empty, saving a timezone always
  failed, and every date in the app fell back to a raw machine-readable
  timestamp. The database is now bundled into the Windows build.

- **The delete confirmation counts contacts, not checkboxes**
  On the duplicates page a contact can appear in more than one group, so
  "delete 5 selected" could precede a delete of three.

- **Ctrl-C stops the server instead of hanging it**
  The server ran on a thread nothing shut down outside the tray's Quit, so
  interrupting a run from the terminal printed an error and then hung,
  still serving, until the process was killed.

- **Google sync no longer discards its own last-sync time when recovering**
  When Google retired a sync token the recovery cleared the whole sync
  record rather than just the token. If the restarted sync then failed
  part-way, the next run could not tell which contacts had local edits
  pending and let Google's copy overwrite them.

- **Pushing a contact to Google preserves birthday entries it does not manage**
  The birthday was the one field written as a wholesale replacement rather
  than an in-place update, so anything else Google held there was
  discarded on every push.

- **A Google sync that fails for want of permission now says so**
  A refused write was counted as an ordinary per-contact skip, so a token
  that had lost its write permission reported every contact as skipped
  with no hint that reconnecting was the fix.

- **System-tray icon now appears when running from source or from a self-built AppImage, not only in CI-built releases** (CL-0057)
  The GI/AppIndicator stack was installed only in the release workflow, so ./run.sh and a local packaging/build-linux.sh both produced a tray-less app — the latter exiting 0 while logging "Hidden import 'gi.repository.DBus' not found". run.sh now builds its venv with --system-site-packages (rebuilding an existing venv once, since the flag is fixed at creation), and build-linux.sh refuses to build under an interpreter that cannot load the GI typelibs rather than silently shipping without a tray. Linux from-source users need a few distro packages — see the README.

- **A non-numeric `CONTACT_LIST_PORT` no longer crashes at startup** (CL-0056)
  It warned nowhere and raised an unhandled `ValueError` while importing
  `config`; it now logs a warning and uses 5002. Its accepted range is
  unchanged.

### Security

- **Search terms are no longer written to the log file, and contact pages are not cached** (CL-0072)
  The request log recorded full URLs, and a contact search puts what you
  typed in the URL — so names, numbers and note text were being written to
  a log file on disk. Contact pages now also set no-store, so they do not
  remain in the browser cache. Contact photos keep their one-day cache.

- **The one third-party release action is pinned to a commit, not a moving tag**
  It runs in the job that holds write access to the repository, and a tag
  can be moved by someone outside GitHub. The GitHub-owned actions stay on
  major tags so they keep receiving fixes.

- **Exported CSV no longer lets contact data run as a spreadsheet formula**
  A contact field beginning with a formula character executed when the
  export was opened in a spreadsheet. Such fields are now neutralised.
  International phone numbers are unaffected.

- **Disconnecting from Google now revokes the token at Google**
  Disconnecting deleted the local copy only, leaving the grant active on
  the Google account — so any surviving copy of the token file still had
  full access to contacts after the user had disconnected.

## [1.1.0] - 2026-07-12

### Added

- **System-tray icon with an Open / Restart / Quit menu (CL-0052).**
  A small icon appears near your clock (Windows, macOS, and Linux). Right-click
  it to open the app in your browser, restart it, or quit — no need to keep the
  browser tab open. Where a desktop has no system tray, the app runs without the
  icon, exactly as before.

## [1.0.0] - 2026-07-12

First public release. Bundles the full feature set built to date into
self-contained one-file downloads for Linux, Windows, and macOS.

### Added

- **Core contact manager — the foundation.**
  Contact CRUD for individuals and companies (name, email, phone, notes),
  user-defined custom fields per contact (EAV model, no schema changes),
  search with type/letter filtering, sorting and pagination, duplicate
  detection and review, and CSV export. Security-hardened throughout:
  parameterized SQL, CSRF tokens on state-changing forms, Jinja2
  autoescaping, a strict Content-Security-Policy, and localhost-only binding.

- **Standalone one-file launchers for Linux, Windows, and macOS.** (CL-0049)
  Download a single file per OS from the GitHub Releases page and run it —
  no Python or dependencies to install. Built automatically by GitHub Actions.

- **Restart and Shutdown server buttons on the Settings page.** (CL-0046)
  For when the app is launched from the desktop icon with no terminal:
  Restart reloads the server with fresh code, Shutdown stops it. Both are
  localhost-only, CSRF-gated, and confirm before acting.

- **Tags / labels for contacts, with filter-by-tag** (CL-0037)
  Group contacts under free-text labels (e.g. "family", "work", "gym"), typed as a comma-separated list on the contact form and shown as chips on the detail page. A filter bar on the contact list narrows to contacts carrying all selected tags (AND). Tags are created on first use and removed when their last contact drops them; merging contacts keeps the union of their tags. No new dependency.

- ****Favourite / pinned contacts (CL-0039).** Star a contact to pin it to the top of the list.** (CL-0039)
  Star the people you contact most and they pin to the top of the contact list (favourites first, then your chosen sort). A star toggle sits on each list row and on the contact page. Favourites are stored locally and never synced to Google.

- ****Honest “Last edited” timestamp.** A per-contact last-edit time that only moves when you edit a contact (never when a Google sync refreshes it), shown on the contact page and as a hint in the list; the footer shows the last Google sync time on every page.** (CL-0033)

- ****Two-way Google sync (CL-0033).** Google Sync now also pushes your changes back: local edits to synced contacts, and brand-new local contacts become new Google contacts. Conflicts (both sides changed since the last sync) resolve by newest edit, with a fresh-etag safety check; multi-valued emails/phones on Google are preserved. Deletions are not pushed. Requires the read-write `contacts` scope — a previously-connected read-only account is detected and prompted to reconnect.** (CL-0033)

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

- **Consistent look across every page, and tabs on the Settings page.** (CL-0047)
  Every page now follows one construction standard: a shared page-header,
  the same "card" panels (the contact add/edit form now matches Settings),
  uniform form fields and buttons. The Settings page groups its sections
  into tabs. Documented in DESIGN.md §10.1.

- **Contact photos are now served as 256 px thumbnails for avatars, not the full-size upload (CL-0035).**
  List and detail avatars display at ~35–56 px but were being sent the entire
  upload (up to 4 MiB). A downscaled 256 px thumbnail is now generated on save
  (via Pillow) and served instead, cutting a typical avatar from megabytes to
  ~20–40 KB. The full-size original is kept on disk unchanged. Photos saved before
  this change get a thumbnail generated lazily on first view. Adds Pillow as a
  runtime dependency (the no-C-extension rule was lifted for this; DESIGN.md §3).

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

- **Google Sync no longer 500s when a synced contact has a photo.** (CL-0045)
  The photo data-access helpers committed the transaction mid-way through
  the per-contact sync savepoint, destroying it, so the sync loop crashed
  with "no such savepoint: person". The helpers now leave committing to
  their caller, matching every other data-access helper.

- **Show the list "Clear" button when filtering by a starting letter** (CL-0043)
  The toolbar Clear guard omitted the `letter` filter, so a letter-only (alpha-nav) or letter+tag view offered no one-click way back to the full list. It now matches the empty-state guard.

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
