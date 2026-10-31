## Files read
All 20 subject files were read in full with `Read`.
- `app.py` — 270/270
- `config.py` — 229/229
- `settings.py` — 147/147
- `launcher.py` — 224/224
- `browser.py` — 44/44
- `server_control.py` — 112/112
- `tray.py` — 61/61
- `resources.py` — 13/13
- `run.sh` — 63/63
- `local-ci.sh` — 164/164
- `scripts/gate.sh` — 39/39
- `.githooks/pre-push` — 154/154
- `packaging/build-linux.sh` — 89/89
- `packaging/build-macos.sh` — 28/28
- `packaging/build-windows.sh` — 15/15
- `packaging/check-version-drift.sh` — 25/25
- `packaging/find-python.sh` — 15/15
- `packaging/make-icons.sh` — 29/29
- `packaging/wine-setup.sh` — 36/36
- `packaging/contact-list.spec` — 130/130

## What I started with
- The global `~/.claude/CLAUDE.md`, the user's email context, and environment details (platform, date).
- A SessionStart hook note about the Ants MCP verbs, and the review-lane prompt.
- The lane block's one-line digest of the project `CLAUDE.md`. I did not have the file itself, a memory index or a git snapshot.

No conflict between the brief and the lane file needed resolving.

## Summary
This is the outer shell of a personal contact-list web app. `app.py` and `config.py` set up the website, its security and its settings. `launcher.py`, `tray.py` and `server_control.py` start it on your own computer, show a tray icon, and handle restart and quit. The shell scripts create the Python environment, run the checks before a push, and build the Linux, Windows and Mac downloads. Most comments are careful and accurate. The real traps are page-size values kept in several places, a few comments that no longer match the code, and a Windows pre-flight build that installs less than the real release does.

## Findings
[Q1] HIGH `config.py:218` — `    MAX_CONTACTS_PER_PAGE = 200` — A stranger raising the ceiling here gets a change that half works. `settings.py:68` accepts the new value, but three literal 200s still cap it silently: `routes/contacts.py:173`, `models.py:259` and `templates/settings.html:92`. Nothing errors, and no comment here names them. — Fix: have the route, model and template read the constant.
Cost: one edit — Searched: `MAX_CONTACTS_PER_PAGE` and `200` across `*.py`, `*.html` and the docs. No name changes; `docs/superpowers/specs/2026-06-30-settings-page-design.md:133` already asks for the constant.
Searched: `\b200\b|per_page` in `models.py`, `routes/*.py`, `templates/*.html`.

[Q1] HIGH `config.py:217` — `    CONTACTS_PER_PAGE = 50` — Nothing reads this. A stranger changing the default page size here changes nothing. The live defaults are `settings.py:46` (`'per_page': '50'`) and `models.py:249`. — Fix: delete it.
Cost: pinned: `docs/superpowers/specs/2026-06-30-settings-page-design.md:37` names it as the then-current state.
Searched: `CONTACTS_PER_PAGE` in `*.{py,html,js,sql}`, no results cut. The only other hit is the `MAX_` read at `settings.py:68`.

[Q1] MEDIUM `packaging/wine-setup.sh:35` — `wine python -m pip install -r requirements.txt pyinstaller` — The Windows build's install list has diverged. `.github/workflows/release.yml:91` also installs `tzdata`, and `contact-list.spec:95-96` calls `collect_all('tzdata')` when `sys.platform == 'win32'`, which is also true under Wine. A stranger trusting this "pre-flight to catch packaging errors" is testing a different build from the one shipped. — Fix: add `tzdata` here, or keep one list of Windows build dependencies.
Cost: one edit — Searched: `tzdata` in `.github`, `requirements*.txt`, `DESIGN.md`. All `packaging/` scripts were read.

[Q4] MEDIUM `launcher.py:109` — `            # (spec INV-4). The INV-4 hand-off below is for a hand launch only.` — "spec" is not named, and at least four specs have an INV-4. The one the same function names, at line 201 (`2026-07-12-system-tray-icon.md`), says at line 463 that `python app.py` stays headless. `2026-08-06-tray-delivery-and-page-opening.md:486` is about no browser when the tray works. The right one appears to be `2026-07-10-standalone-launchers-design.md` (`:624`, single-instance). A stranger changing the hand-off reads the wrong invariant. The bare "spec §4.2" at line 122 and "spec §5" at line 144 have the same problem, since several specs have those sections too. — Fix: name the spec file in each reference.
Cost: one edit — comment only.

[Q4] MEDIUM `launcher.py:63` — `    # Rotating so a long-lived desktop install's log (Werkzeug logs every request` — This is false. `app.py:42` raises Werkzeug to WARNING because those lines leaked search terms (CL-0072). Someone auditing the log for privacy, or debugging a request, would expect request lines that are not there. Line 64's "1 MB x 3 files" is also off: `backupCount=3` keeps four files. — Fix: state the current reason and the count.
Cost: one edit — comment only.
Searched: `werkzeug` in `*.py`; `app.py:42` is the only `setLevel` on it.

[Q4] MEDIUM `launcher.py:163` — `            log.exception('server thread died; shutting down')` — Nothing shuts down. The comment at lines 156-159 says the guard exists because a crash leaves "a live tray icon in front of a dead server", yet after this log line that is still the case. The guard only adds the log entry. A stranger reading the log, or the comment, believes the failure is handled. — Fix: make the message and comment say only that it is logged, or have it stop the tray.
Cost: unsure: the fix is either wording or new behaviour, and I did not search the tests for this log text.
Also listed under Correctness leads.

[Q4] MEDIUM `config.py:80` — `        # O_EXCL plus a temp-and-rename, because the previous read-then-truncate` — The code has no `O_EXCL` of its own (only `mkstemp`'s) and no rename on the normal path. What decides the race is `os.link` at line 96, which fails if the file exists. Line 88 repeats "the O_EXCL race". A stranger "following the comment" could swap `os.link` for `os.replace`, which silently overwrites the winner's key and brings back the CL-0069 failure. — Fix: say `os.link` is the atomic step and why.
Cost: one edit — comment only.

[Q5] MEDIUM `app.py:102` — `        if request.method in ('POST', 'PUT', 'DELETE'):` — This lists the methods to protect, and PATCH is not on it. No comment gives a reason. Anyone adding a PATCH route gets one with no CSRF check and no error. — Fix: exempt the safe methods instead, or say why PATCH is left out.
Cost: one edit — Searched: `_check_csrf` in the docs. `docs/specs/2026-07-01-import-export-merge-design.md:384` names the hook, but the name does not change.
Searched: `PATCH|methods=.*(PUT|DELETE)` in `routes/*.py`, `tests/*.py`, `static/*.js`, `app.py`: no hits, so nothing is exposed today.

[Q2] MEDIUM `config.py:96` — `                os.link(tmp, key_path)` — The thread is lost in lines 91-110, which sit four `try` levels deep. On success, nothing returns here. Control falls through `finally`, past `except OSError`, to the `return key` at line 123, which is also the fallback for a temporary key. The docstring's "stable" is not true on that path. Anyone adding a step for "after a successful save" has no obvious place for it. — Fix: move the persisting step into its own function that returns explicitly.
Cost: one edit — Searched: `_load_or_create_secret_key` in specs and plans (`docs/specs/2026-07-10-standalone-launchers-design.md:101,103,636`, plan `:224`). The name stays.
Candidate: `function_sizes` `config.py:39`.

[Q2] LOW `app.py:75` — `    # CSRF protection` — This banner covers lines 78-185, but only `csrf_token` and `_check_csrf` are about CSRF. Logging, settings loading, the nav count, the footer sync time, template globals and two date filters all sit under it. A stranger looking for the filters by section finds no section; `create_app` loses the thread at line 83. — Fix: add accurate section banners. Moving code out is a larger choice.
Cost: one edit — comment only. Moving hooks out would be pinned: `2026-07-02-two-way-google-sync.md:719,725` and `2026-07-01-import-export-merge-design.md:384` name them.
Candidate: `function_sizes` `app.py:19`.

[Q4] LOW `app.py:90` — `        from db import get_db` — `get_db` is imported inside functions at lines 56, 90, 118 and 136, yet line 15 already imports from `db` at the top of the file. `import settings as settings_mod` repeats at lines 89, 149, 164 and 180. A stranger assumes a circular import and copies the habit, but I can see none: `db.py` imports only stdlib, flask and `resources`, and `settings.py` imports `config` and `phonenumbers`. — Fix: move them to the top, or comment the reason if there is one.
Cost: one edit — Searched: patches of `get_db` in `tests/*.py` (none); no name changes.

[Q1] LOW `app.py:165` — `        s = getattr(g, 'settings', None) or settings_mod.SETTINGS_DEFAULTS` — Three copies, at lines 156, 165 and 181, and nothing says when `g.settings` can be missing. Anyone changing the fallback must find all three. — Fix: one small local helper, with the reason as a comment.
Cost: one edit — Searched: `getattr(g, 'settings'` in `*.py`: only these three.

[Q1] LOW `config.py:99` — `                with open(key_path, encoding='utf-8') as f:` — The second read of the key file has diverged from the first. Lines 62-75 catch `OSError` and `UnicodeDecodeError` with a CL-0069 comment saying why. This read has no decode-error handling, so a stranger who trusts that comment thinks the import-time crash is closed everywhere. — Fix: both reads go through one helper.
Cost: one edit — Searched: `_load_or_create_secret_key` in the docs; no existing name changes.

[Q1] LOW `settings.py:57` — `    'sort': {'name', 'type', 'created', 'updated'},` — This set is kept by hand in three places: here, `models.py:274-279` (`allowed_sorts`) and `templates/settings.html:97`. All match today. Add a sort to the first and third but miss `models.py`, and it silently sorts by name (`models.py:280`). Density, view, direction and default type are also hand-copied into `settings.html`. The `THEMES` comment at lines 35-36 makes "derived" look like the rule. — Fix: pass the choices to the template and derive the model's keys or check them against this set.
Cost: one edit — Searched: `_ALLOWED` in the docs (only a plan's snippet, `docs/superpowers/plans/2026-07-01-settings-page.md:188`); no rename.

[Q1] LOW `launcher.py:115` — `        open_url(f'http://127.0.0.1:{port}')` — The local address is written out in many places. The URL is at `launcher.py:115,153,212`, `tray.py:36` and `app.py:266`, and the bind address at `launcher.py:52,104,146` and `app.py:270`. A change to how the address is built would miss some. — Fix: one shared URL helper or constant in `config.py`.
Cost: one edit — Searched: `http://127\.0\.0\.1:\{` in `*.py`; a new name, nothing renamed.

[Q1] LOW `packaging/check-version-drift.sh:11` — `code_ver="$(grep -oE "APP_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'" config.py | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)"` — Three copies of the pattern: here, `.github/workflows/release.yml:39` and `.claude/bump.json:3`. Allowing a pre-release version, or changing the quote style, means finding all three, and a miss fails only at release time. — Fix: have `release.yml` reuse the script's extraction.
Cost: one edit — Searched: `APP_VERSION` in `.github` and `.claude/bump.json`; nothing renamed.

[Q4] LOW `config.py:9` — `# the top CHANGELOG heading must match this — packaging/check-version-drift.sh` — This says the script enforces both the tag and the CHANGELOG. It checks only the CHANGELOG. The tag check is a separate step at `.github/workflows/release.yml:35-45`. A stranger could delete that step as a duplicate. — Fix: name both enforcers.
Cost: one edit — comment only.

[Q4] LOW `.githooks/pre-push:61` — `        # New branch: diff against origin/HEAD's tip if we know it, else the` — The code uses `origin/main` and has no fallback to the commit's parent; line 68 just runs CI. The next code line corrects the reader. — Fix: describe what the code does.
Cost: one edit — comment only.

[Q4] LOW `launcher.py:168` — `    # The thread is non-daemon and only the tray's Quit calls server.shutdown(),` — This describes the old bug in the present tense ("The process hangs"), while the handler just below also calls `server.shutdown()`. So it reads as a current defect and contradicts itself. — Fix: lead with the current rule, one clause on what it prevents.
Cost: one edit — comment only.

[Q4] LOW `launcher.py:207` — `        # "Listening on" line above may go nowhere (stdout is None). This is the ONLY` — The claim of "the ONLY start-path open" sits in the same function as the open at line 115, and `run.sh:59` says "the only two". A stranger might take line 115 as a leftover and remove it. `tests/test_launcher_no_autoopen.py:84` asserts an open on that path, so a run would show it. — Fix: say "the only open on a path that binds the port".
Cost: one edit — comment only.

[Q4] LOW `launcher.py:185` — `    if os.environ.get('LWSM_MANAGED') == '1':` — The comment says what the variable does, but not what LWSM is or who sets it. `README.md:135` gives its behaviour and no expansion, in the rows I read. A stranger checking whether a change affects managed runs has to ask. — Fix: name the manager in one line.
Cost: one edit — comment only.

[Q4] LOW `packaging/find-python.sh:5` — `# an empty PY would otherwise run the next line's heredoc as a command named "-".` — This file has no heredoc. The only one is in `make-icons.sh:8`, one of three scripts that source this file. — Fix: name that script.
Cost: one edit — comment only.

[Q4] LOW `packaging/contact-list.spec:92` — `# timestamp in the app degrades to a raw ISO string. Build-time only (§3 keeps` — "§3" names no document, in a file whose other references do name theirs. It means `DESIGN.md` §3. — Fix: name it.
Cost: one edit — comment only.

[Q3] LOW `server_control.py:65` — `        from browser import _system_env` — The underscore says private to `browser.py`, whose docstring is about opening a browser. But the restart child's environment depends on it too. A stranger tuning it "for xdg-open" would silently change restarts. — Fix: give it a public name, in a neutral home.
Cost: pinned: `docs/specs/2026-07-05-server-restart-control.md:96` names `browser._system_env()`. `tests/test_browser.py:7,14` also calls it.

## Candidates dismissed
- `launcher.py:91:main` (130 lines) — About half is comments, and the steps run in order with early returns. I could not name a line where the thread is lost. Its stale comments are filed above.
- `settings.py:106:update_settings` (42) — Clear three-step flow, with the order explained.
- `server_control.py:79:_run_after_delay` (34) — Mostly docstring; the body is short.
- `config.py:17` "64 characters" — Correct: `token_hex(32)`.
- `launcher.py:64` "3 files" — Confirmed; filed inside the `launcher.py:63` finding.
- `local-ci.sh:55`, `packaging/build-linux.sh:10`, `packaging/wine-setup.sh:24`, `run.sh:34` — Download sizes and timings. I cannot measure them here, and they are marked approximate.
- `local-ci.sh:109` "3 requires" — Not a count; it is "`DESIGN.md` §3 requires".

Also considered, and not findings:
- `run_step` in `local-ci.sh` and `step` in `gate.sh` are two copies, with no sign a past fix touched both.
- `fetch_verify` in `build-linux.sh` and its inline copy in `wine-setup.sh` differ only in the timeout, and I found no fix that had to patch both.
- `.claude/bump.json` is tracked (`.gitignore:21`), so `config.py`'s pointer to it is good.

## Correctness leads
- `config.py:92` — `os.fchmod` was only added on Windows in Python 3.13, and the Windows release job uses 3.12. There is no platform guard. A likely result is no saved secret key on each Windows launch, or a crash at import. — Searched: `release.yml` `python-version`; `fchmod|sys\.platform.*win|os\.name` in `*.py`.
- `config.py:99` — A `UnicodeDecodeError` here escapes at import, which is the failure CL-0069 fixed for the first read. — Searched: none.
- `config.py:64` — A stored key of any length is accepted, while an env key must meet `MIN_SECRET_KEY_LEN`. — Searched: none.
- `launcher.py:174` — With the tray running, SIGTERM or SIGINT stops the server but not `icon.run()`. The process may stay alive with an icon in front of a dead server. — Searched: none.
- `launcher.py:163` — With a tray, a crashed server thread leaves the icon up and the process alive. — Searched: none.
- `packaging/wine-setup.sh:35` — The missing `tzdata` probably makes the Wine build fail at `collect_all`, or ship with no timezone data. I do not know which. — Searched: `tzdata` in `.github`, `requirements*.txt`, `DESIGN.md`.
- `.githooks/pre-push:57` — The `break` here and at lines 69 and 78 stops collecting `pushed`, so later refs in the same push skip the "is it HEAD?" check at line 116. — Searched: none.
- `local-ci.sh:159` — The tree is hashed after the checks finish, so a file edited during the run is recorded as having passed. — Searched: none.
- `packaging/build-linux.sh:52` — A corrupt cached download fails its checksum on every run and is never re-fetched, and nothing tells the user to delete it. `wine-setup.sh:26` does the same. — Searched: none.
- `.github/workflows/release.yml:22` (outside this lane) — The comment says `.gitignore` excludes `bump.json`, but `.gitignore:21` un-ignores it. — Searched: `.gitignore`.

## Not checked
- **`pystray` and GI lists:** whether `Gtk` and `Gio`, which the `build-linux.sh` probe requires but `hiddenimports` omits, reach the bundle another way. That depends on `pystray` and PyInstaller hooks I did not read.
- **Library behaviour:** what `collect_all` does for a missing package, and the `os.fchmod` result on real Windows. Both come from my own knowledge, not a run here.
- **Searches cut short:**
  - Three `workspace_search` calls stopped at their row limits (`truncated: true`), and I did not page through the rest: `INV-*`/`LWSM`, the multi-name settings search, and `create_app`/`PATCH`.
  - The spec-section `Grep` stopped at 40 rows and the `CL-0056`/`LWSM` `Grep` at 30.
  - So "at least four specs have an INV-4" is a floor, and the `LWSM` expansion may exist in a row I did not read.
  - The `PATCH` and `CONTACTS_PER_PAGE` findings rest on later searches that were not cut, within the file types named in those findings.
- **Other limits:** `DESIGN.md` §3's drift requirement (`local-ci.sh:109`) was not confirmed, and no scripts were run. I did not open `contacts.db` or `~/.config/contact-list/`.
