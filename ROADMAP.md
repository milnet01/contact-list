<!-- ants-roadmap-format: 1 -->

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

- ✅ [CL-0046] **Add in-app Restart / Shutdown server controls on the Settings page.**
  Launched from a desktop icon (run.sh -> exec python app.py, no
  terminal, debug=False so no reloader), the user has no Ctrl-C. Restart
  = self re-exec (os.execv fresh python app.py); Shutdown = os._exit(0).
  Deferred on a daemon thread so the HTTP response flushes first; guarded
  against firing under pytest. POST /settings/server, CSRF-gated,
  localhost-only. Spec: docs/specs/2026-07-05-server-restart-control.md
  (spec passed /cold-eyes, 5 loops).
  **Layman:** Buttons on the Settings page to restart or stop the server, so you don't need a terminal when you launch from the desktop icon.
  Kind: feature.
  Source: user-request-2026-07-05.
  Resolved (2026-07-05): Settings page has Restart + Shutdown buttons. Restart respawns a fresh detached python app.py via subprocess.Popen (close_fds drops the inherited Werkzeug socket) then os._exit(0) — in-place os.execv was tried and failed (Werkzeug marks its listen socket inheritable, serving.py:1105, so it survives execve and blocks rebind); found by a real port-5099 smoke test. Deferred on a daemon thread (guarded under pytest), CSRF-gated, localhost-only, data-confirm modal. 355 tests green + end-to-end smoke test.

- ✅ [CL-0047] **Page construction standard: one consistent look across all pages, tabs on Settings.**
  Establishes a documented page-construction standard (page_header
  macro, card sections, .form-group/.form-actions forms, button
  placement, tabs) and migrates every page to it — the contact edit form
  gains the Settings card look; Settings sections become tabs. Spec:
  docs/specs/2026-07-05-page-construction-standard.md (spec passed /cold-eyes, 6 loops).
  **Layman:** Make every page look and feel like the Settings page, and put the Settings sections into tabs.
  Kind: refactor.
  Source: user-request-2026-07-05.
  Resolved (2026-07-05): page_header macro (_macros.html), base fieldset now renders as a card (matches Settings), .form-group forms + .form-actions, .card-title, .page-header, and progressive-enhancement tabs (app.js separate IIFE, tab-bar hidden until .js-tabs, type=button, roving tabindex, Save hidden on Server tab). Settings sections are tabs; contact form + all pages migrated; contact_detail keeps its .detail-header variant. Spec passed 6-loop /cold-eyes. 356 tests green (+1), all templates compile + render 200, app.js valid, CSS balanced. DESIGN.md §10.1 records the standard. Manual visual QA pending (no browser automation here).

- ✅ [CL-0048] **app.js single-IIFE early return strands back-to-top / --header-h on most pages.**
  static/app.js is one big IIFE (lines 2-534). The custom-fields
  block does `if (!container || !addBtn) return;` at line 347, which
  returns from the WHOLE IIFE. So on any page without #custom-fields
  (Settings, contact list, detail, sync, import, merge, duplicates,
  birthdays) everything after line 347 never runs — including the
  back-to-top button wiring and the --header-h sticky-header height calc
  the list page's sticky filter bar relies on. Fix: split app.js into
  independent per-feature IIFEs (or replace the early return with a guarded
  block) so one absent element can't disable later features. Found while
  restructuring app.js for CL-0047 settings tabs.
  **Layman:** The 'back to top' button and the sticky filter-bar positioning silently don't work on most pages (everywhere except the contact add/edit form).
  Kind: fix.
  Source: surfaced-during-CL-0047 cold-eyes 2026-07-05.
  Resolved (2026-09-07): the sticky-header height calc and the
  back-to-top wiring now live in their own IIFE, alongside the tabs
  block that was already separated for the same reason. Verified: the
  file parses under `node --check`, and the moved code sits outside the
  IIFE carrying the custom-fields early return. Found again independently
  by two lanes of a full review sweep, which also established the exact
  extent — `--header-h` is set only on the contact form and consumed only
  on the contact list, so the measurement never reached the page that
  needed it and the sticky bar always used its hardcoded fallback.
  Two defects in the moved lines were fixed with it: the deprecated
  `pageYOffset` alias, and a smooth scroll that ignored
  `prefers-reduced-motion` despite DESIGN.md §10 promising support.

- ✅ [CL-0049] **Standalone one-file launchers per OS (AppImage / .exe / .dmg) via PyInstaller + GitHub Actions.**
  Design: docs/specs/2026-07-10-standalone-launchers-design.md. Freeze the Flask app with PyInstaller into one self-contained artefact per OS; GitHub Actions runners build all three (Linux/Windows/macOS can't cross-build), with local pre-flight builds on Linux (native) and Windows (Wine). Key code changes: frozen-aware data dir (~/.config/contact-list), resource_path helper for bundled templates/static/migrations, and --google-auth self-dispatch so OAuth works in the frozen binary. macOS ad-hoc-signed arm64 .dmg (unsigned/no-notarization out of scope). Cutting v1.0.0 is a separate follow-on.
  **Layman:** A single download-and-run file for Linux, Windows, and Mac so anyone can use the app without installing Python or any dependencies.
  Kind: package.
  Source: user-request-2026-07-10.
  Design spec signed off 2026-07-10 after /cold-eyes converged (6 loops, 2 cold reviewers/loop; polish-only at loop 6, zero CRITICAL/HIGH). Spec: docs/specs/2026-07-10-standalone-launchers-design.md. Pending user review before the implementation plan.
  Resolved (2026-07-10): standalone launchers implemented across 10 TDD tasks + a whole-branch review, all on main. Code: resources.py (resource_path), frozen DB path (config.py), _auth_command dispatch (routes/sync.py), launcher.py entrypoint, favicon PNG. Packaging: contact-list.spec, make-icons.sh, build-linux.sh (AppImage; pre-fetches the AppImage runtime via curl + --runtime-file to dodge appimagetool's hanging downloader), build-windows.sh + wine-setup.sh (Wine pre-flight), build-macos.sh (CI-only). CI: .github/workflows/release.yml — dry-run built Linux+Windows+macOS all green on real runners (Linux needed desktop-file-utils). Verified: AppImage + Wine .exe launch and serve; frozen data lands in ~/.config/contact-list; frozen Google auth completes end-to-end. 364 tests green, ruff+mypy clean. Follow-on (separate): tag/publish the first release + reconcile CL-0050.

- ✅ [CL-0050] **CHANGELOG [1.0.0] says "Initial public release" but was never tagged/published.**
  Found during CL-0049 cold-eyes. CHANGELOG.md:166-169 has a dated [1.0.0] - 2026-06-30 section labelled "Initial public release", but there is no git tag, GitHub Release, or binary. Reconcile as part of the release follow-on (tagging): either the current [Unreleased] items fold into the real 1.0.0 first publish, or 1.0.0 is retroactively marked and the new work ships as 1.1.0.
  **Layman:** The release notes claim version 1.0.0 was released, but it never actually was (no download exists). Reword when we cut the real first release.
  Kind: doc-fix.
  Source: cold-eyes-2026-07-10 (CL-0049 spec review).
  Resolved (2026-07-12): folded [Unreleased] + the never-published [1.0.0] foundation into one [1.0.0] - 2026-07-12, tagged v1.0.0, and pushed. GitHub Actions built and published the first release with all three self-contained binaries (AppImage / .exe / .dmg). Added APP_VERSION to config.py (shown in footer) + packaging/check-version-drift.sh + .claude/bump.json recipe.

- ✅ [CL-0052] **System-tray icon with right-click Open / Restart / Quit menu (cross-platform).**
  Add a system-tray/menu-bar icon (via pystray) with a right-click menu: Open Contact List, Restart, Quit. Tray owns the main thread; the web server moves to a stoppable background-thread handle. Graceful fallback to today's headless behaviour where no tray is available. Scope: frozen app AND from-source (run.sh routes through launcher.py). Raises DESIGN.md §3 dep budget to 8 (pystray, justified like Pillow). Design: docs/specs/2026-07-12-system-tray-icon.md. Linux tray backend + AppImage bundling being grounded by a deep-research pass first (highest-risk area). Must pass /cold-eyes before implementation.
  **Layman:** A little icon by the clock so you can open, restart, or quit the app without hunting for its window — on Windows, macOS, and Linux.
  Kind: feature.
  Source: user-request-2026-07-12.
  Progress (2026-07-12): deep-research pass complete (run wf_0fe49d44-bb6, 24 confirmed claims / 21 sources); §4/§6 finalised — Linux backend = pystray appindicator (SNI over DBus; xorg rejected, no menu), AppImage bundling via PyInstaller 6.3.0+ built-in GI hooks. Spec cold-eyes converged after 7 cold loops to polish-only (verdict "implementable as-is"); Status → REVIEWED. Awaiting user sign-off before writing-plans / implementation.
  Shipped in v1.1.0 (2026-07-12). Cross-platform system-tray icon (Open/Restart/Quit) via pystray; server moved to a stoppable background thread, tray owns the main thread; graceful headless fallback. Verified on KDE Wayland (tray icon + menu + Quit work). Two verification-found bugs fixed en route: frozen browser-open LD_LIBRARY_PATH leak (browser.py open_url), and the missing DBus GI typelib (hiddenimports). Reviewed per-task + final whole-branch (Ready to merge).

- ✅ [CL-0056] **PORT and LWSM_MANAGED env vars for an external process manager.**
  config.resolve_port() resolves PORT -> CONTACT_LIST_PORT -> 5002 and is
  called at both bind sites (launcher.py, app.py __main__), so the value
  reaching make_server/app.run is the derived one. PORT must be an integer
  in [1024, 65535]; an invalid value exits non-zero naming the value rather
  than falling back silently. CONTACT_LIST_PORT keeps its behaviour and its
  (absent) range, and no longer raises at import on a non-integer. Every
  binding path prints "Listening on http://127.0.0.1:<port>" to stdout (a
  print, not a log — the frozen path logs to a file). INV-4's
  single-instance hand-off is split: PORT-supplied + busy exits non-zero
  with no browser; PORT absent is unchanged. LWSM_MANAGED=1 skips the tray
  only (branch taken before the tray try/except so the fallback log stays
  truthful); it gates nothing else.
  **Layman:** An external tool can now tell the app which port to use and ask it to run without its taskbar icon, without anyone editing the code.
  Kind: feature.
  Source: user-request-2026-08-06.

- 📋 [CL-0059] **A working tray icon with Open / Restart / Quit, on the paths users actually run.**
  Requested 2026-08-06. NOTE for whoever picks this up: the menu itself is
  already written and shipped — tray.py:55-61 builds exactly "Open Contact
  List" (opens http://127.0.0.1:<port>), "Restart" (server_control.schedule)
  and "Quit" (server.shutdown + icon.stop), delivered by CL-0052. Do NOT
  rebuild it. The gap is delivery, not the feature: verified 2026-08-06 that
  the icon appears on NEITHER the from-source run NOR a locally built
  AppImage, because the GI/AppIndicator stack is installed only in the
  release workflow (CL-0057). Fix CL-0057 first, then confirm this one by
  observing a real icon rather than by reading tray.py. Acceptance: an icon
  is visible near the clock after ./run.sh on a stock desktop, its three
  items do what they say, and Quit releases the port (INV-1).
  **Layman:** The app should show an icon near the clock with options to open it in the browser, restart it, or shut it down — and that icon needs to actually turn up, not just exist in the code.
  Kind: fix.
  Source: user-request-2026-08-06.

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

- ✅ [CL-0044] **Re-baseline or retire DESIGN.md §14 "Total pip install < 20 MB" budget row.**
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
  Resolved (2026-09-07): took both options the bullet offered, split by
  row. Measuring first showed the problem was wider than the bullet knew
  — EVERY row was breached, not just the pip one, including the row
  already labelled a soft target.

  Re-baselined the four source rows against measured figures, dated, with
  the commands that reproduce them, so the next reader re-derives instead
  of trusting. Dropped the other two: an empty SQLite database measures
  nothing meaningful and never said whether it meant before or after
  migrations, and no size figure could have been a control for the pip
  install, because the budget that actually governs is §3's eight-package
  direct limit. Stating it twice gave two answers that could disagree.

  Also stated outright that nothing checks any of these — no test asserts
  one and no CI step reads the table — because reading as a live gate
  while universally breached is what made the row misleading rather than
  merely wrong.

  CLAUDE.md rule 14: applied the test. Correcting stale counts is the
  exemption's own named case. Dropping the two rows is closer to the
  line, so under the grey-zone rule it is recorded here rather than
  gated: a wrong no is self-correcting on this document's next real gate,
  and neither row instructed anyone to do anything a reader now does
  differently.

- ✅ [CL-0051] **Bump actions/upload-artifact and actions/download-artifact v4 → v5 in release.yml (Node 20 deprecation).**
  The v1.0.0 release run surfaced deprecation annotations: actions/upload-artifact@v4 (build-linux/windows/macos) and actions/download-artifact@v4 + softprops/action-gh-release@v2 (release job) target Node.js 20, force-run on Node 24 for now. Per DESIGN.md deps-latest policy, bump upload-artifact and download-artifact to @v5; re-check action-gh-release for a newer major. checkout@v7 / setup-python@v6 are already current.
  **Layman:** The release build works but GitHub warned that two of its helper steps use an old, soon-to-be-removed engine. Updating them now avoids a hard failure later.
  Kind: chore.
  Source: in-session-2026-07-12 (v1.0.0 release run annotations).
  Resolved (2026-07-12): bumped upload-artifact v4→v7, download-artifact v4→v8, action-gh-release v2→v3 (all pure Node 20→24 runtime moves; verified against each major's release notes — no caller changes). workflow_dispatch rehearsal on main went green across all three OS build jobs with no Node 20 deprecation annotation remaining. checkout@v7 / setup-python@v6 already current.

- ✅ [CL-0053] **Update `server_control.py:42` restart docstring — still says "python app.py", now stale since `run.sh` execs `launcher.py`.**
  **Layman:** A code comment about restarting the server still names the old startup file; harmless but should be updated to match the new launcher.
  Kind: doc-fix.
  Source: in-session-2026-07-12 CL-0052 Task 5.
  Resolved inline in CL-0052 Task 5 — the server_control.py restart docstring now describes the sys.argv[0] respawn accurately (launcher.py from source / frozen binary when frozen).

- 📋 [CL-0054] **Harden the restart-respawn against the launcher port-check race.**
  After CL-0052 repointed run.sh through launcher.py, the restart child (subprocess spawn of sys.argv[0]) now passes through launcher's _port_is_serving short-circuit. If the child checks the port before the parent's os._exit(0) releases it, the child opens a browser and exits, leaving no server running — a silent failure (the old app.py path failed loudly with 'Address already in use'). Effectively unreachable in practice (~microsecond os._exit vs ~100ms child startup) but worth hardening: e.g. have the restart child skip the short-circuit, or retry-with-backoff on the bind. Found by the CL-0052 final whole-branch review.
  **Layman:** A rare timing quirk on Restart could in theory leave the app closed instead of reopening; make Restart robust against it.
  Kind: fix.
  Source: in-session-2026-07-12 CL-0052 final-review.

- 💭 [CL-0055] **Benign GTK "Failed to load module" messages on terminal launch (no clean fix).**
  The frozen AppImage's bundled GTK reads the user's ~/.config/gtk-3.0/settings.ini, sees KDE's gtk-modules=colorreload-gtk-module:window-decorations-gtk-module, and can't load them from its own bundled module path -> two "Gtk-Message: Failed to load module" lines on stderr. Fully benign (the appindicator tray is windowless; those modules are theme integration). Invisible on desktop-icon launch (no terminal). Investigated: no clean fix — the module list is settings-file-sourced (GTK unions it with the env var, so GTK_MODULES cannot subtract), and the messages are emitted by GTK's C layer to fd2 (can't be filtered from Python without hiding real errors). Pointing the bundled GTK at host modules (GTK_PATH) risks ABI mismatch and isn't portable. Decision: leave as-is unless a clean, portable lever surfaces (e.g. a future pystray/GTK option to skip modules).
  **Layman:** When the app is started from a terminal on some Linux desktops, GTK prints two harmless "couldn't load module" notes; you never see them launching from the desktop icon.
  Kind: investigate.
  Source: in-session-2026-07-12 CL-0052 verification.

- ✅ [CL-0057] **The tray icon is a CI-release-only feature: both the from-source and the local-build paths ship without it.**
  The GI/AppIndicator stack is installed in exactly ONE place —
  .github/workflows/release.yml:26-27 (apt gir1.2-ayatanaappindicator3-0.1,
  python3-gi, GTK) plus its --system-site-packages build venv at line 36,
  all added by a32547b, which touched no packaging script.
  packaging/build-linux.sh contains no --system-site-packages at all; its
  only venv reference is line 7, `for c in ./venv/bin/python python3
  python`, which picks the same gi-less ./venv that run.sh:9-11 creates.
  CI escapes this only because it exports PYTHON=build-venv/bin/python.
  So BOTH non-CI paths lose the tray:

    - From source: ./run.sh logs "system tray unavailable or failed" with
      ImportError: this platform is not supported: No module named 'gi'.
      Verified pre-existing on an unmodified tree (git stash) 2026-08-06.
    - Local AppImage: `bash packaging/build-linux.sh` exits 0 while logging
      "ERROR: Hidden import 'gi.repository.DBus' not found" and the same for
      AyatanaAppIndicator3; the resulting .AppImage serves normally, opens
      the browser, registers NO StatusNotifierItem on the session bus, and
      writes the same ImportError to ~/.config/contact-list/contact-list.log.
      Verified on a built artefact 2026-08-06, not inferred.

  Consequence for the spec: §10's local-build verification step ("launch the
  resulting .AppImage from a clean environment") cannot confirm the tray —
  it never appears there — so it is not a usable pre-release check for
  CL-0052's feature, and INV-3's silent fallback hides all of this.
  Decide between: (a) --system-site-packages in run.sh AND build-linux.sh
  (+ document the apt/zypper prerequisite), or (b) declare the tray a
  release-build-only feature and make INV-3's fallback say so out loud
  instead of logging at INFO. Blocks CL-0059.
  **Layman:** The taskbar icon only exists in the version built by the release robot. Run the app from the source folder, or build it yourself, and it silently starts with no icon at all.
  Kind: fix.
  Source: in-session-2026-08-06 (CL-0056 hand-verification; root cause corrected by the user 2026-08-06 — the earlier diagnosis wrongly named packaging/build-linux.sh).
  Progress (2026-08-06): specced as docs/specs/2026-08-06-tray-delivery-and-page-opening.md (umbrella with CL-0060), accepted after /cold-eyes converged by cap — 3 loops, 2 cold lanes each, 60 findings verified and closed. User chose option (a): --system-site-packages in run.sh (with a one-time rebuild of the existing gi-less venv) plus a loud GI pre-flight in packaging/build-linux.sh, and the distro prerequisite documented. The build script creates no venv of its own, so the flag lands only in run.sh. Prerequisite packages installed on this machine and the approach proven end to end: a --system-site-packages venv running launcher.py registered a real tray item on the session bus (Id 'contact-list', Status Active). Note for the implementer: the pre-flight must probe Gtk 3.0, Gio 2.0 AND DBus 1.0 plus either indicator typelib — DBus is what commit 3c817fc already fixed once — and release.yml's apt list must gain gir1.2-gtk-3.0 and the freedesktop typelib in the same commit, or the new gate can turn a release red.
  Resolved (2026-08-06): run.sh builds its venv with --system-site-packages (rebuilding an existing one once, guarded on both the pyvenv.cfg marker AND the base interpreter still running), plus --ignore-installed at creation so our pinned Flask/Pillow stay in the venv rather than being borrowed from the distro. build-linux.sh gained a pre-flight probing every namespace pystray needs (Gtk 3.0, Gio 2.0, DBus 1.0, AppIndicator3-or-Ayatana), which captures stderr so the failure names the missing typelib. release.yml gained gir1.2-gtk-3.0 + gir1.2-freedesktop so the new gate cannot redden a release on a transitive-dependency change. VERIFIED on real artefacts, not inferred: ./run.sh rebuilt the venv and registered a tray item on the session bus, and a locally built AppImage did the same with no ImportError in its log and no 'Hidden import gi.repository.DBus' line in the build. Follow-up CL-0061 filed for 60 spurious PyInstaller hidden-import errors the gi-capable venv introduces (noise, not breakage).

- ✅ [CL-0058] **Spec INV-6 cites app.py:211 for the loopback bind; the line has moved.**
  docs/specs/2026-07-10-standalone-launchers-design.md INV-6 says
  "matching app.py:211"; the app.run call is at app.py:230 after CL-0056
  (was 217 before it). Pre-existing drift — the citation was already
  stale before this change. Left alone to stay in lane.
  **Layman:** A design document points at a line number in the code that has since shifted, so a reader following the reference lands in the wrong place.
  Kind: doc-fix.
  Source: in-session-2026-08-06 (CL-0056).
  Resolved (2026-09-07): fixed by removing the line number rather than
  correcting it. The bind had moved to app.py:230, then 231, then 244
  during this session's own edits — three moves for one citation, which
  is the argument against the whole form. Every `app.py:<line>` reference
  in docs/specs/ now names the symbol instead (`create_app`'s
  `app.run(host='127.0.0.1', ...)` call, `_check_csrf`, `init_db`,
  `Flask(__name__)`, the `test_config` argument), so none of them can go
  stale on an edit elsewhere in the file.

  The bullet named INV-6's citation; the sweep found the same defect in
  every sibling reference, all equally stale, so they were fixed together
  rather than leaving known-wrong pointers beside a corrected one.

  Two dead anchors found next door and fixed with them: both table-of-
  contents links omitted a heading's trailing parenthetical. Verified by
  doc_integrity over the four edited specs — zero findings.

- ✅ [CL-0060] **Open question: should a manager-started server open a browser at all?**
  launcher.py:106 fires the browser-open on EVERY start that binds,
  including one driven by an external process manager. Deliberate as of
  CL-0056: the user ruled it out of scope ("the manager's problem to solve,
  not yours") and specifically forbade suppressing it via LWSM_MANAGED,
  which may change only whether the tray icon appears -- it is
  unauthenticated, trivially forged and inherited by children, so gating
  anything else on it is a security smell. The decision is the user's and
  is still open; if it lands as "no browser under management", it needs its
  OWN signal, not LWSM_MANAGED. Do not implement either way without asking.
  Evidence available: pointing BROWSER at a recording script during CL-0056
  verification showed exactly one open per managed start (see CLAUDE.md
  "Verifying a launch by hand" for the technique).
  **Layman:** When an external tool starts the app, a browser window pops up. Whether that should happen is still undecided.
  Kind: investigate.
  Source: in-session-2026-08-06 (user's open decision, recorded before context clear).
  Resolved (2026-08-06): decided by the user and specced in docs/specs/2026-08-06-tray-delivery-and-page-opening.md. The site is NOT opened automatically — "I don't want the site automatically opened. That is why I wanted the tray icon or LWSM to be able to open the page." The startup auto-open (_open_when_ready + _OPEN_DEADLINE_S) is deleted outright. Two narrow exceptions survive, both user-initiated or last-resort: the single-instance hand-off still opens on a second launch (the user confirmed one instance at a time), and a start whose TRAY FAILS opens the browser, because the review found that without it a frozen windowed build on a tray-less desktop (GNOME without an extension) would have no icon, no tab and no visible URL — _emit no-ops when console=False — leaving a running server the user cannot reach. Crucially this needs NO new signal: the managed path returns before the tray block, so LWSM_MANAGED still gates only the tray icon and nothing was built on an unauthenticated variable. Locked by INV-4, INV-8 and INV-9.
  Resolved (2026-08-06): _open_when_ready and _OPEN_DEADLINE_S deleted along with the daemon poll thread; the surviving open sits inside the tray-failure except branch only. A start whose tray comes up opens nothing (INV-4); a start whose tray fails opens the page (INV-8), because a frozen windowed build has no console to print its URL to and would otherwise be unreachable; a managed start opens nothing either way (INV-9), since it returns before the tray block. No new env var or flag was needed, so nothing is gated on the forgeable LWSM_MANAGED beyond the tray icon. VERIFIED with the browser-open recorded rather than merely unobserved: both ./run.sh and the built AppImage opened nothing on a normal start.

- 📋 [CL-0061] **The gi-capable build venv makes PyInstaller emit 60 spurious "Hidden import not found" errors.**
  Introduced by CL-0057, verified on a real build 2026-08-06. Not breakage: the
  artefact is correct (dist/Contact-List/_internal/google/auth/__init__.py is
  present, and the built AppImage serves and registers its tray), so this is a
  diagnostics problem, not a functional one.

  Cause: `google` is a NAMESPACE package. Once run.sh creates the venv with
  --system-site-packages, google.__path__ gains /usr/lib64/python3.13/
  site-packages/google as its FIRST entry, and that directory has no `auth`
  subpackage. PyInstaller resolves the explicit hiddenimports entries against
  that first path, fails, and logs "ERROR: Hidden import 'google.auth' not
  found" plus 59 more. At runtime Python's namespace machinery searches every
  path entry, so `import google.auth` works (confirmed from ./venv/bin/python),
  and PyInstaller still collects the package via the normal dependency graph
  from google_sync.py, which is why the bundle is complete.

  Why it matters despite being harmless: CL-0057 itself was diagnosed by
  spotting ONE "ERROR: Hidden import 'gi.repository.DBus' not found" line in
  build output. Sixty false ones of the same shape make the next real one
  invisible. That DBus line is now gone (verified: the hidden import analyses
  cleanly), so the regression this replaces is fixed, but the signal it lived
  in is degraded.

  Likely fix: give PyInstaller the venv's site-packages ahead of the system one
  (a --paths argument, or pathex in packaging/contact-list.spec) so the
  namespace package resolves venv-first. Verify by counting "ERROR: Hidden
  import" lines in a clean build: 60 today, expected 0. Do NOT "fix" it by
  dropping --system-site-packages, which would reintroduce CL-0057.
  **Layman:** The AppImage builds correctly, but the build now prints 60 scary-looking errors that are not real — and that noise could hide a genuine one next time.
  Kind: fix.
  Source: in-session-2026-08-06 (CL-0057 implementation, found by reading the build log).
  Progress (2026-09-07): still open, but two routes are now ruled out by
  measurement rather than reasoning, and the bullet's own diagnosis needs
  correcting.

  The cause is not path ORDER. The distro ships site-packages/google as
  a REGULAR package (an `__init__.py` calling pkgutil.extend_path), and
  under PEP 420 a regular package found anywhere on sys.path beats the
  namespace portions on earlier entries. So `google` resolves to the
  distro copy regardless of ordering.

  Ruled out: (a) the `pathex` / `--paths` fix this bullet proposes --
  tried, still sixty errors, because ordering is not the lever;
  (b) dropping `google.auth` from the spec's collect_all loop on the
  grounds that the dependency graph collects it anyway -- it does not.
  That silences all sixty errors and produces a bundle with no
  _internal/google/ directory at all.

  The bullet's premise that this is "not breakage" was half right. The
  artefact was NOT correct: the sixty lines were hiding a genuinely
  missing `google.oauth2`, which made /sync return 500 in the frozen app.
  That is fixed and recorded as CL-0080; this item is now only about the
  remaining log noise.

  Untried ideas for whoever takes it: a PyInstaller hook that resolves
  the namespace portions explicitly, or filtering the unresolvable
  entries out of hiddenimports after collect_all returns.

- 📋 [CL-0062] **Decide which of ruff 0.16's 35 newly-flagged findings to adopt.**
  Context: pyproject.toml had no [tool.ruff.lint] select, so ruff used its
  implicit default. Ruff 0.16 widened that default, so the routine bump from
  0.15.21 to 0.16.1 turned a clean run into findings across sixteen rules that
  nobody had opted into. Resolved on 2026-08-06 by stating the historical set
  (E4, E7, E9, F) explicitly, so the tool tracks latest while the lint contract
  is a deliberate choice. Verified the explicit set still catches real defects
  (F401 unused import, F821 undefined name).

  This item is the follow-up question that split off: WHICH of the wider rules
  do we actually want? Measured with `ruff check . --output-format=concise` at
  0.16.1 with select unset:

  ```
  7 I001      import block un-sorted
  5 RUF059    unused unpacked variable
  5 BLE001    blind `except Exception`
  4 DTZ011    `date.today()` without a timezone
  2 UP037     redundant quotes in a type annotation
  2 UP017     `datetime.UTC` alias available
  2 LOG015    logging call on the root logger
  1 each      UP012, S310, RUF100, RUF012, PLW1510,
              LOG014, FURB162, EXE001, B017
  ```

  BLE001 is the one to be careful with: launcher.py's tray fallback is
  deliberately blind and should stay that way.

  Some look genuinely valuable (S310 flags a URL open, DTZ011 naive datetimes).
  Others would fight deliberate design. Treat this as a review of each rule
  family, adopting per-rule with a `# noqa` plus reason where the current code
  is right, NOT as a bulk autofix: thirteen are auto-fixable and seven more
  need --unsafe-fixes, which is exactly the shape that quietly changes
  behaviour.
  **Layman:** A newer version of our code checker suggests improvements it never used to mention. Worth reading through and picking the ones we want, rather than accepting or ignoring them wholesale.
  Kind: refactor.
  Source: in-session-2026-08-06 (dependency sweep; surfaced by the ruff 0.15 to 0.16 bump).

- 📋 [CL-0063] **Restart respawns the AppImage from a mount that is being unmounted.**
  Frozen, both `sys.executable` and `sys.argv[0]` are the AppImage
  type-2 runtime's ephemeral mount. server_control spawns the child from
  that path and then `os._exit(0)`s the payload, at which point the
  runtime unmounts it -- so the child, a onedir bundle still paging in
  the stdlib, dies part-started. Two consequences ride along: because
  `sys.executable == sys.argv[0]` when frozen the command is the binary
  with its own path as argv[1], and re-exec'ing the old mount reloads the
  OLD code even when an update succeeded, which is the stated purpose of
  restart.

  QUEUED RATHER THAN FIXED: the remedy (prefer `$APPIMAGE`) changes what
  two invariants of docs/specs/2026-07-05-server-restart-control.md
  describe. INV-1 pins the respawn argv to `sys.executable` + `sys.argv`,
  and INV-3's port-rebind reasoning was verified on the source path only
  -- its own note records a port-5099 smoke test, which cannot have
  covered the frozen case. So this needs the spec amended and gated
  before the code moves, not an inline edit during a fix pass.

  Blocked-by: a spec amendment to 2026-07-05-server-restart-control.md.
  **Layman:** Restarting the app from the tray or the Settings page probably kills it instead, on the Linux download most people use.
  Kind: fix.
  Source: review-code 2026-09-07 (process-lifecycle lane); queued by close-findings.

- 📋 [CL-0064] **Decide whether clearing a field locally should push the deletion to Google.**
  A field the user empties is omitted from both the request body and
  `updatePersonFields`, so Google never hears about it and keeps the old
  value; the next pull then re-imports that value locally and the
  deletion silently reverts. The spec's conflict rule promises "local
  wins", and under this a clearing edit can never win. The same shape
  applies to the birthday, address and organization custom fields.

  QUEUED RATHER THAN FIXED: this is a decision, not an edit. Pushing an
  empty value deletes data on the Google side, which is exactly what
  INV-2 ("a push never removes a value the app does not manage") is
  guarding against -- so the two readings pull opposite ways and the
  wrong choice destroys data. Settle the semantics, record them in the
  spec, then implement.
  **Layman:** If you delete someone's phone number here, Google keeps its copy and puts it back on the next sync.
  Kind: investigate.
  Source: review-code 2026-09-07 (google-sync lane); queued by close-findings.

- 📋 [CL-0065] **DESIGN §6 covers input handling only; nothing states an output-encoding rule.**
  The CSV formula-injection fix landed in code (`_csv_safe`), but §6.1
  is entirely about the inbound direction, so nothing tells the next
  person writing an export to neutralise anything. The same gap covers
  vCard emission and any future export format.

  QUEUED RATHER THAN FIXED: adding the rule changes what a conformer
  writes, which is rule 14's Yes branch, so it needs `review-contract`
  rather than an inline edit during a fix pass.
  **Layman:** Our security standards say how to handle data coming in, but not how to make it safe on the way out.
  Kind: security.
  Source: review-code 2026-09-07 (routes-io lane); queued by close-findings.

- 📋 [CL-0066] **Contact list pays a full table scan and per-row phone parsing on every render.**
  Four findings, one subject -- all measured against DESIGN §7.1's own
  targets:

    - `get_letter_counts` groups on `first_letter(name)`, a Python
      callback registered in db.py. SQLite cannot index an
      application-defined function, so every contact-list render scans
      the table with one interpreter round trip per row, and the
      `?letter=` filter scans the same way. §7.2 promises indexes on
      WHERE/ORDER BY columns; a UDF in the predicate defeats that by
      construction. Remedy: a stored first-letter column, indexed.
    - `find_duplicates` and `find_all_duplicates` run
      `phoneutil.normalize_e164` per row with no caching, on every
      contact create and update. Remedy: store the E.164 form in an
      indexed column.
    - `idx_contacts_email` can never be used: every email lookup wraps
      the column in LOWER() and search uses a leading-wildcard LIKE. It
      is maintained on every write and serves nothing.
    - `/contacts/duplicates` and `/contacts/birthdays` neither paginate
      nor bound their result set, against §7.2's "all list endpoints
      paginate".

  Found independently by two lanes.
  **Layman:** The contact list does far more work per page than it needs to, and it gets worse as the address book grows.
  Kind: perf.
  Source: review-code 2026-09-07 (data-layer + routes-contacts lanes).

- 📋 [CL-0067] **Both exports buffer the whole database in memory, against DESIGN §7.2.**
  §7.2 requires streaming responses for CSV and vCard export, using
  generators rather than full in-memory buffers. Both do the opposite:
  `export_contacts` calls `.fetchall()`, the CSV route builds a
  `StringIO` and returns `getvalue()`, and `vcard.emit` assembles one
  string from a complete list. The vCard route additionally issues a
  `get_custom_fields` query per contact -- an N+1 that dominates a large
  export.

  The code is the wrong side here: §7.2's wording ("any future CSV/vCard
  export") predates the export shipping, and it shipped buffered.
  **Layman:** Exporting contacts builds the entire file in memory before sending it, which the design document says not to do.
  Kind: perf.
  Source: review-code 2026-09-07 (data-layer + routes-io lanes).

- 📋 [CL-0068] **Request-derived values reach loops and writes with no server-side bound.**
  Four sites, one subject. The choke-point pattern already exists in
  this codebase -- `_normalize_tags` enforces its caps in the model, so
  every caller gets them -- and these four skipped it:

    - `merge_apply` takes `cf_count` straight from the form and uses it
      as a loop bound, with no clamp.
    - `bulk_delete` takes an unbounded id list, each costing its own
      commit and a full orphan-tag anti-join.
    - `name`, `email`, `notes` and custom-field values have no
      server-side length limit at all; the only caps are the browser
      `maxlength` attributes, which a direct POST ignores.
    - The 50-custom-field cap lives only in the contact route, so the
      CSV/vCard import path reaches `import_contact` uncapped.

  Calibrated below the lanes' raw severity: this is a single-user
  localhost app, so the requester is the owner. The import path is the
  exception and keeps its weight -- that input is genuinely untrusted.
  Progress (2026-09-07): PARTLY done, deliberately not flipped.

  Done: the four core-field length caps and the fifty-custom-field limit
  now live in models.py and are applied at all three write sites, so the
  CSV and vCard import paths get them too -- that was the bypass this
  item was mainly about. merge_apply's cf_count is clamped to the same
  cap. Verified through import_contact as well as create_contact, with
  regression tests proven red.

  Still open: bulk_delete's id list is still unbounded, each id costing
  its own commit and a full orphan-tag anti-join.

  Note: the commit that landed this work cites CL-0067 in its subject and
  body. That is wrong -- CL-0067 is the buffered-exports item. The id was
  miscopied; the work described here is this bullet's. Recorded rather
  than rewritten, since the commit is already pushed.
  **Layman:** A few form fields are trusted to be a sensible size without anyone checking.
  Kind: security.
  Source: review-code 2026-09-07 (routes-contacts + data-layer + routes-io lanes).

- 📋 [CL-0069] **Secret-key persistence and the config directory have gaps a fresh install can hit.**
  Four findings in `config.py`, one subject:

    - The secret-key write is read-then-write with no `O_EXCL` and no
      atomic rename. Two copies started at once on a fresh install each
      mint a different key and each truncate-overwrite; the loser then
      403s every POST -- the exact failure the persisted key was
      introduced to fix. A crash mid-write leaves a zero-byte file,
      which the read treats as absent and silently rotates the key.
    - The read catches `FileNotFoundError` only, so a `PermissionError`
      or a decode error escapes -- at import, before file logging is
      installed, on a build whose stdout is None. The app fails to start
      with no message anywhere.
    - `ensure_private_dir` chmods only the leaf, so the config directory
      itself is created 0755 by the nested caller. It is normally
      tightened as a side effect of persisting the secret key -- but
      that branch is skipped entirely when `SECRET_KEY` is set, which
      the README advertises, and DESIGN §8.1 tells the user to put
      `credentials.json` there.
    - `SECRET_KEY` from the environment has no length floor.
  Progress (2026-09-07): PARTLY done, deliberately not flipped.

  Done: the secret-key write is now a temp file plus os.link, so whoever
  wins owns the file and every other worker re-reads the winner's key --
  closing both the concurrent-first-run race and the zero-byte-file
  rotation. The read now catches OSError and UnicodeDecodeError rather
  than FileNotFoundError alone, so an unreadable key file no longer kills
  the app at import with no message on any surface. Verified with eight
  concurrent callers converging on one key; tests proven red.

  Still open, both from the same lane: ensure_private_dir chmods only the
  leaf, so the config directory itself is created 0755 by its nested
  caller -- and the branch that normally tightens it as a side effect is
  skipped entirely when SECRET_KEY is set, which the README advertises.
  And SECRET_KEY from the environment still has no length floor.
  **Layman:** The file that keeps you logged in can be written twice at once on first run, and the folder holding your Google credentials is briefly readable by other users on the machine.
  Kind: security.
  Source: review-code 2026-09-07 (app-core lane).

- 📋 [CL-0070] **Google sync robustness: SSRF redirect, rate limits, and a lock held across a download.**
  Six findings in `google_sync.py`, one subject:

    - The photo host allow-list validates only the INITIAL URL.
      `urlopen` follows redirects by default, so a 3xx from an approved
      host to a local address is followed. The guard is the documented
      SSRF mitigation and does not survive a redirect. (The guard is
      otherwise sound -- userinfo, trailing-dot and confusable hosts all
      fail closed.)
    - No rate-limit handling anywhere: no `num_retries`, no 429 branch.
      The spec mandates a one-time bulk create of every local-only
      contact, which is exactly where the write quota trips.
    - The photo download runs inside the per-contact SAVEPOINT, holding
      the write lock across a network call with a socket timeout and no
      total budget.
    - The photo is re-fetched on every upsert; nothing stores the photo
      URL or an etag, so an unchanged photo is indistinguishable from a
      new one.
    - The deferral check precedes the deleted-tombstone check, so a
      tombstone for a locally-edited contact is skipped and consumed by
      that run's sync token, never redelivered. The local row survives
      as an orphan pointing at a deleted resource.
    - A transient network failure is indistinguishable from an invalid
      grant, so a temporary outage invites a full re-auth.
  **Layman:** The Google sync has several rough edges that show up on large address books or slow networks.
  Kind: security.
  Source: review-code 2026-09-07 (google-sync lane).

- ✅ [CL-0071] **Photo writes are not atomic and can destroy the existing photo on a failed replace.**
  Two findings in `photos.py`:

    - `save_photo` deletes the previous file BEFORE opening the new one
      for writing. If that write fails, the old photo is already gone
      while the database still names it, so the avatar 404s permanently.
      The thumbnail path a few lines up does this correctly, with a temp
      file and `os.replace` -- the original does not.
    - The thumbnail temp name is unique per PROCESS, not per writer. Two
      concurrent requests for the same avatar share one temp path, so
      one can truncate the file while the other is between write and
      rename, promoting a half-written image that then persists because
      the existence check never regenerates it. The docstring's
      atomicity claim is true of the rename and false of the temp file.
  Resolved (2026-09-07): both halves. save_photo now writes the new
  file to a temp and os.replace's it into position before removing the
  old one, so a failure in between can no longer leave the contact with
  no photo while the database still names one. _write_thumbnail uses
  tempfile.mkstemp instead of a per-process name, so two concurrent
  regenerations of the same avatar cannot share a path and promote a
  half-written image.

  Verified by simulating the failure rather than reasoning about it: with
  os.replace raising, the existing photo is still present and
  byte-identical and no temp file is left behind. Regression tests proven
  red against the old code -- the preservation test failed with
  FileNotFoundError, because the old photo was already gone.
  **Layman:** Replacing a contact photo deletes the old one first, so if the new one fails to save you lose both.
  Kind: fix.
  Source: review-code 2026-09-07 (google-sync lane).

- ✅ [CL-0072] **Contact search terms are written to the log file, and pages carrying contact data are cacheable.**
  Two findings, both privacy rather than a breach:

    - The root logger is pinned to INFO, which is the level Werkzeug's
      request logger uses, so every request line -- including the query
      string -- is logged. Contact search covers name, email, phone and
      notes, and on a frozen build those lines persist to a rotating log
      under the config directory. No document says that file holds
      contact data, and the file is created with the process umask
      rather than 0600 as the token file is. Remedy: raise the Werkzeug
      logger's level, or strip the query string.
    - No `Cache-Control` header is set, so contact detail pages land in
      the browser's on-disk cache. Remedy: `no-store` on the response.

  Found by two lanes independently.
  Resolved (2026-09-07): both halves. Werkzeug's own logger is raised to
  WARNING rather than the root's, so the request line carrying the search
  query string is no longer written to the log file while our own INFO
  lines are unaffected. Contact pages set Cache-Control: no-store.

  Applied with setdefault so the photo route's deliberate one-day
  max-age (CL-0034) is untouched -- verified on the running app: the
  photo response still carries public, max-age=86400 while the page it
  sits on carries no-store.
  **Layman:** What you type into the search box gets written to a log file on disk, and contact pages can sit in the browser cache.
  Kind: security.
  Source: review-code 2026-09-07 (app-core + process-lifecycle lanes).

- 📋 [CL-0073] **The confirmation dialog on every destructive action has no dialog semantics.**
  The modal gates delete contact, bulk delete, disconnect Google,
  restart server and shut down server. It carries no `role`, no
  `aria-modal` and no `aria-labelledby`, so the question in the message
  paragraph is never announced; there is no Escape handler and no focus
  trap, and nothing restores focus to the trigger on cancel.

  Related accessibility findings from the same two lanes, same subject:
  the file input and the column-mapping selects on the import page have
  no labels; the merge page's tags input lost the label its twin on the
  contact form has; the merge radio groups have no fieldset/legend; the
  sortable column headers convey state only by a glyph, with no
  `aria-sort`; the three single-character keyboard shortcuts have no
  modifier guard, so Ctrl+S is swallowed; and the selection count
  changes with no live region.

  The project names no accessibility standard, so none of these was
  raised above the level general principles support.
  **Layman:** Someone using a screen reader is asked to confirm deleting a contact and hears only "Confirm, button" — never what they are deleting.
  Kind: accessibility.
  Source: review-code 2026-09-07 (templates + frontend-js lanes).

- 📋 [CL-0074] **DESIGN §9's route table is missing a third of the shipped routes.**
  Three lanes found this independently, each from a different side.
  Absent from §9: the birthdays page and the import page -- both
  TOP-LEVEL NAV ITEMS -- plus import apply, vCard export, bulk delete,
  merge preview and merge apply. §9.1 also omits the `ref` parameter,
  and its stated "default 50" for page size is really the user's
  Settings value.

  The document is the wrong side: §13 already marks the work shipped.
  A favourites spec from July recorded the gap as pre-existing and it
  was never closed.

  This is a contract document, so the edit runs rule 14's test before it
  lands.
  **Layman:** The design document's list of web addresses the app answers is well out of date.
  Kind: doc-fix.
  Source: review-code 2026-09-07 (routes-contacts, routes-io and templates lanes).

- 📋 [CL-0075] **vCard export loses standard fields to a private property, and drops them on import.**
  Four findings, one subject -- all about fidelity to other software
  rather than to ourselves:

    - Birthday, address and organization are modelled as first-class
      concepts in DESIGN §8.2 and named explicitly in the Google sync
      code, yet every custom field exports as a private `X-CL` property
      no other consumer reads. The import side is the mirror: inbound
      `BDAY` and `ADR` match no branch and are dropped. Round-trips
      within this app, loses the data to every other app.
    - A company card emits no `N` property, which RFC 2426 makes
      REQUIRED in vCard 3.0; strict consumers reject the card.
    - `emit` never folds long lines, which RFC 6350 says it SHOULD. The
      import side unfolds correctly.
    - The parser ignores `ENCODING=QUOTED-PRINTABLE`, which Android
      exports still use heavily. The module docstring scopes itself to
      3.0/4.0, so the code matches its own contract -- whether the
      contract should widen is a product call.

  The group-prefix and CR-escaping halves of this lane's findings were
  fixed on 2026-09-07 and are not part of this item.
  **Layman:** Birthdays and addresses exported from here are not recognised by other contact apps, and theirs are ignored by ours.
  Kind: fix.
  Source: review-code 2026-09-07 (routes-io lane).

- 📋 [CL-0076] **Five production modules are outside mypy's file list, including both untrusted-text parsers.**
  `[tool.mypy]`'s `files` list omits `importer.py`, `photos.py`,
  `server_control.py`, `tray.py` and `vcard.py`. Three lanes noticed
  independently, and the sharpest framing is that the two modules
  parsing untrusted text are the two never type-checked -- `vcard.py`'s
  heterogeneous dicts being exactly what mypy is good at.

  Adding them may surface a batch of errors, which is why this is its
  own item rather than a line in a fix pass.

  Same subject, from the same lanes: no route function carries a return
  annotation, and several helpers take untyped parameters, against
  CLAUDE.md's "type hints on all signatures". Neither tool catches it as
  configured -- ruff selects a narrow set with no ANN rules, and mypy
  runs without `disallow_untyped_defs`. Widening the ruff select is
  already tracked separately, and BLE001, PLW1514 and PTH would each
  have caught findings this sweep found by hand.
  Progress (2026-09-07): PARTLY done, deliberately not flipped.

  Done: all five modules -- importer.py, photos.py, server_control.py,
  tray.py and vcard.py -- are in mypy's file list. The checked set went
  from seventeen files to twenty-two with zero new errors, so they were
  correctly annotated all along and simply never checked. A comment on
  the list now says a new module belongs there on the day it is written.

  Still open: the other half of this item. No route function carries a
  return annotation and several helpers take untyped parameters, against
  CLAUDE.md's requirement of type hints on all signatures. Neither tool
  catches it as configured -- ruff selects no ANN rules and mypy runs
  without disallow_untyped_defs. Turning either on is the real fix and is
  its own piece of work.
  **Layman:** The type checker skips five of our files — including the two that read files other people send us.
  Kind: chore.
  Source: review-code 2026-09-07 (five lanes).

- 📋 [CL-0077] **JavaScript, templates and the PyInstaller spec are analysed by no tool at all.**
  Reported as a gap in the static-analysis tool set rather than as a
  review win, because a tool should have decided each of these:

    - There is no `package.json`, so no JavaScript row is ever selected
      and `static/app.js` is checked by nothing. A linter would have
      found a variable declared twice in one scope, a second IIFE
      missing `'use strict'`, and a deprecated scroll alias.
    - No template-aware or HTML-aware tool runs, and the semgrep packs
      used are Python-only, so the Jinja templates are checked by
      nothing.
    - `packaging/contact-list.spec` is Python that neither ruff nor
      mypy recognises by extension. Under the project's own selected
      rule set every PyInstaller-injected global in it would raise an
      undefined-name finding.

  Remedy is a decision about tooling, not an edit: adding a JS linter
  means adding a Node toolchain to a project that deliberately has no
  build step, which is a trade worth making deliberately.
  **Layman:** Our automated checks cover the Python and shell code but not the browser code, the page templates, or the packaging script.
  Kind: chore.
  Source: review-code 2026-09-07 (frontend-js, templates and shell-ci lanes); gap in check-code's tool set.

- 📋 [CL-0078] **Shell and CI: several failure paths report success.**
  The two worst findings in this lane -- the push gate silently skipping
  CI, and the cached test environment never updating -- were fixed on
  2026-09-07. What remains, same subject:

    - `run.sh` omits the `--ignore-installed` its own venv-creation step
      uses, so a dependency the distro also ships is borrowed from the
      system rather than taking our pinned version.
    - `run.sh` runs under `set -e` with an unconditional per-launch pip
      install, so with PyPI unreachable an app that worked yesterday
      will not start at all.
    - `check-version-drift.sh` fails closed on a malformed version, but
      under `set -e` a failed extraction exits before its own diagnostic
      can print, so the messages naming the problem are unreachable.
    - The interpreter-search prologue is duplicated three ways across
      the packaging scripts and only one copy has the empty-interpreter
      guard the tray spec explains.
    - `wine-setup.sh` runs a downloaded installer with no integrity
      check, and re-runs a cached copy unverified -- while the Linux
      build script establishes the project's own pattern of pinning a
      checksum and re-verifying every run.
    - The push hook decides docs-only from the commits being pushed but
      runs the gate against the working tree.
    - Nothing makes the release path depend on CI, which triggers on
      branch pushes only -- so a tag push publishes binaries without
      ever running the checks.
  **Layman:** A few of our build and launch scripts carry on as if nothing went wrong when something did.
  Kind: fix.
  Source: review-code 2026-09-07 (shell-ci lane).

- 📋 [CL-0079] **Several smaller correctness and UI defects across routes, templates and the frontend.**
  Filed as one item because each is small and none needs a decision.
  The full lane reports carry the detail.

    - A photo write failure raises after the contact has already been
      saved, so the user sees an error page and cannot tell the contact
      was kept -- contradicting that function's own docstring.
    - A failed custom-field row vanishes from the re-rendered form, so
      the error names a field no longer on the page.
    - The edit form's error re-render omits the photo state, so a ticked
      "remove photo" is lost silently on resubmit.
    - The merge flow is a second copy of the contact-field validation
      that never received the email, phone and region normalisation the
      original has -- so merge can write values the contact form itself
      rejects.
    - The birthdays page is the only date in the app not rendered
      through the shared filter, so it ignores the user's chosen date
      format and depends on the server's locale.
    - Card view applies its masonry layout to the first group only on
      the duplicates page.
    - An armed confirmation button stays armed if navigation does not
      complete, so the next click submits unconfirmed.
    - Inline SVG icons are stamped repeatedly with three different
      class treatments, which is the drift the page-construction
      standard exists to stop, and the shared macro file holds only the
      page header.
    - Timezone lookups walk the whole zone database on every settings
      render and again per submitted value, uncached.
  **Layman:** A list of small things that are wrong but not urgent.
  Kind: ux.
  Source: review-code 2026-09-07 (all lanes); the Low tail.

- ✅ [CL-0080] **Google sync was dead in the frozen build: google.oauth2 was never bundled.**
  Found by launching a locally built artefact and opening the page,
  which is the only way it could have been found: every static check and
  every one of the 428 tests passes, because they all run from source
  where the import resolves.

  Symptom: `GET /sync` returned 500 in the frozen app, with
  `ModuleNotFoundError: No module named 'google.oauth2'` in
  ~/.config/contact-list/contact-list.log. `is_authenticated` is called
  on that page, and it reaches `_token_has_write_scope`, which imports
  `google.oauth2.credentials`.

  Cause, and it is the same one as CL-0061 one layer deeper. `google` is
  a namespace package. run.sh builds its venv with
  --system-site-packages, which CL-0057 requires so the tray can import
  the system PyGObject, and the distro ships its own
  site-packages/google as a REGULAR package -- an `__init__.py` calling
  pkgutil.extend_path. Under PEP 420 a regular package found anywhere on
  sys.path wins outright over the namespace portions on earlier entries,
  so `google` resolved to the distro copy, which carries neither `auth`
  nor `oauth2`. PyInstaller could not see either. `google.auth` was
  listed in the spec's collect_all loop and so was bundled anyway;
  `google.oauth2` was not listed, google_sync.py imports it only inside
  function bodies, and nothing else dragged it in.

  Fix: name `google.oauth2` in the collect_all loop alongside
  `google.auth`. Verified on a real artefact -- /sync, /contacts and
  /settings all 200, no errors in the frozen app's log.

  This is what CL-0061 predicted: sixty spurious "Hidden import not
  found" lines per build made a real one invisible. The real one was not
  even in that list, because the missing import was never declared.

  OPEN QUESTION for whoever picks up CL-0061: whether the CI-built
  release was affected too. release.yml's build-linux also uses
  --system-site-packages, so it depends on whether ubuntu-latest ships a
  regular `google` package the way this openSUSE box does. Not settled
  here; it needs a CI build to answer.
  **Layman:** In the downloadable app, opening the Google Sync page showed an error instead of the page. It never worked there.
  Kind: fix.
  Source: in-session-2026-09-07 (found by running a frozen build during verify-delivery, not by reading).

- 📋 [CL-0081] **Hand-verifying a launch needs the CONFIG dir isolated, not just the database.**
  CLAUDE.md's "Verifying a launch by hand" carries three traps -- poll
  for the port, background the server, intercept the browser-open. There
  is a fourth and it bites harder, because its damage lands outside the
  repository.

  CONTACT_LIST_DB isolates the database and NOTHING ELSE. PHOTOS_DIR,
  GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE and the log all derive from
  config._CONFIG_DIR, which has no environment override. So a run that
  looks isolated because the database is:

    - writes uploaded photos into the user's real photos directory, and
    - on any page calling is_authenticated -- /sync is one -- REFRESHES
      AND REWRITES the user's real Google token, because _load_credentials
      calls creds.refresh() and _save_credentials writes it back.

  Both happened in this session. The photo files were orphans and were
  removed; the token rewrite is not reversible and was reported to the
  user. It is not damaging -- a refresh rotation is normal and the
  credentials still work -- but it is a live-credential side effect
  nobody asked for, and the standing rule is that a check needing a
  credential is an ask.

  The remedy is to set XDG_CONFIG_HOME to a scratch directory for any
  hand-verification run, which moves _CONFIG_DIR wholesale, rather than
  overriding CONTACT_LIST_DB alone. A frozen build needs this even more
  than a source run, because frozen also puts its database there.

  This belongs in CLAUDE.md's "Verifying a launch by hand" list, next to
  the other three. Filed here rather than edited straight in because
  adding it changes what a conformer does -- they would isolate a
  directory they do not isolate today -- which is rule 14's Yes branch
  and owes the review gate. Small edit, one gate; worth doing.
  **Layman:** A note for future sessions: testing the app by running it can touch your real Google login and photo folder unless the whole settings folder is pointed somewhere else.
  Kind: doc.
  Source: in-session-2026-09-07 (learned the expensive way during verify-delivery).

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
