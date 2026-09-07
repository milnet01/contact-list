# Lane 4 — app-core (app.py 232, config.py 181, settings.py 106, phoneutil.py 35, resources.py 13)
## Critical (0)
## High (1)
- [dim 2] settings.py:60 + app.py:146 + routes/settings.py:30 — Windows has no system tz database; CPython zoneinfo falls back to the tzdata PyPI package, and tzdata appears NOWHERE in the tree (not requirements.txt, not contact-list.spec's collect_all). On the shipped Contact-List.exe available_timezones() returns an empty set: the Settings timezone select renders with zero options, every timezone save fails, and ZoneInfo('UTC') raises ZoneInfoNotFoundError which app.py:151 swallows — so EVERY timestamp renders as the raw ISO string. Two documented features dead on a documented platform, silently. fix: add `tzdata; sys_platform == "win32"` to requirements.txt and 'tzdata' to the spec's collect_all.
  ORCHESTRATOR VERIFICATION: CONFIRMED by reading — tzdata absent from all three files; DESIGN 15 ships Contact-List.exe. Not executed on Windows.
## Medium (6)
- [dim 16] config.py:48-54 — except FileNotFoundError only on the secret-key read; PermissionError, IsADirectoryError, UnicodeDecodeError escape, and this runs in the Config class body at IMPORT, before _install_file_logging(). A frozen windowed build has stdout/stderr None, so a config dir restored from backup makes the app fail to start with no message anywhere. Breaks the module's own rule at config.py:88-91.
- [dim 9] config.py:56-59 — read-then-write with no O_EXCL and no atomic rename. Two copies started concurrently on a fresh install each mint a different key and each O_TRUNC-overwrite; the loser 403s every POST — the precise failure config.py:37-41 claims persistence fixed. A crash between truncate and write leaves a zero-byte file, silently rotating the key.
- [dim 3] config.py:23 — ensure_private_dir chmods only the LEAF; intermediates get 0o777 & ~umask. The nested caller app.py:52 creates ~/.config/contact-list at 0755 and tightens only photos/. Normally locked earlier as a side effect of persisting the secret key — but that branch is SKIPPED when SECRET_KEY is set (config.py:43-45), which README:128 advertises. On that path the dir stays world-readable while DESIGN 8.1 tells the user to put credentials.json there.
- [dim 15] app.py:30-33 — logging.basicConfig pins the ROOT level, which Werkzeug's request logger uses; it logs the full request line including the query string, and /contacts?q=... searches name, email, phone and notes. On the frozen build these persist to contact-list.log with no redaction and no document saying that file holds contact data.
- [dim 7][tool: ruff] app.py:75,:101,:121 — three except Exception blocks; the first swallows with NO log line. A missing settings table silently reverts the user's timezone/theme/per_page on every request forever. BLE001 would catch all three; pyproject selects only E4,E7,E9,F.
- [dim 17] app.py:151 — IANA retires zones (Europe/Kiev -> Europe/Kyiv). A timezone validated at write time becomes unresolvable after a tzdata upgrade, and friendly_date then returns the raw ISO string app-wide, permanently and silently; get_settings does no re-validation on read.
## Low / Info
- [dim 3] app.py:82 — allow-by-default method list missing PATCH. 14 mutating routes are all POST today, so nothing bypasses it; the next PATCH route is unprotected with no error.
- [dim 3] app.py:24-27 — app.config.update(test_config) REPLACES from_object(Config) rather than layering, so a dict caller gets no MAX_CONTENT_LENGTH, no SESSION_COOKIE_SAMESITE, no MAX_CONTACTS_PER_PAGE.
- [dim 2] DOC SIDE — specs cite app.py:211 for the loopback bind; ROADMAP CL-0058 says app.py:230; it is now app.py:231. The bind itself is correct and is the only listen path.
- [dim 2] config.py:102-111 — CONTACT_LIST_PORT accepts any integer, so 0/-1/99999 dies with a raw OverflowError where PORT gets a clean message and exit 2.
- [dim 4] settings.py:56 — reads Config.MAX_CONTACTS_PER_PAGE while routes read current_app.config; the two copies diverge for any create_app(test_config).
- [dim 2][tool: mypy] app.py:159,:180,:184,:188 no type hints; :126 unparameterised dict.
- [dim 2][tool: ruff] config.py and resources.py are os.path throughout against python.md's pathlib idiom; PTH not selected.
- [dim 5] app.py:69-78 — _load_settings unconditional, so /static/* each open SQLite and query settings.
- [dim 13] app.py:145 — a stored timestamp without a zone yields a naive datetime and .astimezone() assumes the MACHINE's zone. Unreachable today (every writer uses the Z-suffixed default); one non-Z write from being a wrong-time bug.
- [dim 3] app.py:158-173 — no Cache-Control, so contact detail pages land in the browser's on-disk cache.
- [dim 3] config.py:43-45 — SECRET_KEY from env taken with no length floor; SECRET_KEY=x is a one-byte signing key, and README:128 advertises it.
- [dim 2b] No zombies. Every declared entry point has a live non-test caller (enumerated).
## Covered by spec and looks correct
CSP at app.py:160-167 matches DESIGN 6.3 character for character including no unsafe-inline. CSRF: secrets.token_hex(32), constant-time compare_digest, fails closed on empty either side, app-level before_request registered before the blueprints; all 14 mutating routes are POST and 16 template form sites ship the hidden field. Loopback bind is the literal 127.0.0.1 and the only listen path. Port contract matches CHANGELOG and README exactly on all four clauses. debug=False passed explicitly so the Werkzeug debugger cannot be enabled from the environment. phoneutil catches only NumberParseException, region validated against SUPPORTED_REGIONS, phonenumbers caps input length itself.
## Open questions
- app.py:66-67 _log_request logs at DEBUG while root is INFO, so it never emits, and Werkzeug already logs the same line. Leftover or future flag?
- get_settings re-validates nothing on read — intentional?
- config.py justifies the persisted key by "multiple worker processes" and no multi-worker path exists in the tree.
## 3 to fix first
1. Missing tzdata on Windows. 2. ensure_private_dir tightening only the leaf. 3. The secret-key read/write pair.
