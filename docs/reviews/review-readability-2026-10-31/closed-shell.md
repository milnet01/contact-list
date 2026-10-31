# Shell lane: closed (CL-0107)

| finding (file:line) | disposition | was -> now, or why, or roadmap id |
|---|---|---|
| config.py:218 MAX_CONTACTS_PER_PAGE | moved to routes-sync | constant kept; route, model and template reads belong to that lane |
| config.py:217 CONTACTS_PER_PAGE | fixed | unread constant deleted. No red run: nothing observable changes |
| wine-setup.sh:35 tzdata | fixed | `tzdata` added to the pip line. No red run: build script |
| launcher.py:109 (and :122, :144) bare "spec" | fixed | each names its spec file. No red run: comment only |
| launcher.py:63 Werkzeug log claim | fixed | states live file + 3 backups, and that request lines are not logged. No red run: comment only |
| launcher.py:163 "shutting down" | fixed | message and comment say the guard only logs. Behaviour (stop the tray) queued: CL-0108 |
| config.py:80 O_EXCL comment | fixed | `os.link` named as the atomic step, with a do-not-swap warning |
| app.py:102 PATCH | fixed | exempts safe methods. Red: PATCH test returned 405, not 403 |
| config.py:96 four-level try | fixed | split into `_persist_secret_key` (explicit returns) and `_read_key_file` |
| app.py:75 CSRF banner | fixed | banner renamed, CSRF note added. No red run: comment only |
| app.py:90 inner imports | fixed | `get_db` and `settings` imported at top; no cycle (db, settings import nothing from app). `import models` left inside `create_app` |
| app.py:165 settings fallback x3 | fixed | `current_settings()` helper. No red run: refactor, covered by existing tests |
| config.py:99 second read | fixed | both reads use `_read_key_file`. Red: UnicodeDecodeError on an undecodable key file |
| settings.py:57 sort set x3 | queued | CL-0109 (touches models and templates, other lanes) |
| launcher.py:115 loopback URL x many | dismissed | taste: the literal address is the localhost-only contract (DESIGN.md 6.3), and a shared builder adds indirection to a security boundary |
| check-version-drift.sh:11 pattern x3 | fixed | script takes an optional tag; release.yml calls it. `.claude/bump.json` runs the script, so it is no longer a third copy. Checked by hand |
| config.py:9 comment | fixed | names both checks, now true |
| pre-push:61 comment | fixed | describes merge-base with origin/main |
| launcher.py:168 comment | fixed | leads with the current rule |
| launcher.py:207 "ONLY" | fixed | "only open on a path that binds the port" |
| launcher.py:185 LWSM | fixed | says a process manager sets it (README). The expansion is not in the repo, so none was invented |
| find-python.sh:5 heredoc | fixed | names make-icons.sh |
| contact-list.spec:92 "§3" | fixed | "DESIGN.md §3" |
| server_control.py:65 `_system_env` | fixed (comment) | rename pinned by a dated spec and tests; browser.py docstring now says restarts use it |
| lead config.py:92 fchmod on Windows | fixed | real bug; `os.fchmod` dropped (mkstemp is already 0600). Red: AttributeError. CHANGELOG [Unreleased] |
| lead config.py:99 decode error | fixed | see the config.py:99 row |
| lead config.py:64 stored key length | dismissed | the file is written by the app (64 chars); the floor guards a human-typed env value |
| lead launcher.py:174 SIGTERM with tray | queued | CL-0108 (needs a pystray stop hook, no display here) |
| lead launcher.py:163 crash with tray | queued | CL-0108 |
| lead wine-setup.sh:35 tzdata | fixed | see the tzdata row |
| lead pre-push:57 `break` | queued | CL-0110 |
| lead local-ci.sh:159 hash after run | queued | CL-0110 |
| lead build-linux.sh:52 corrupt cache | queued | CL-0110 (wine-setup.sh:26 too) |
| lead release.yml:22 comment | fixed | stale `.gitignore` claim removed |
| candidates dismissed by the lane | dismissed | as the lane file says |

Docs made stale by the PATCH fix and updated: CLAUDE.md and DESIGN.md CSRF lines.

Sweep: searched `O_EXCL`, `CONTACTS_PER_PAGE`, `POST/PUT/DELETE`, `INV-4` and `_check_csrf` across code, README, DESIGN.md and CLAUDE.md. Found the CSRF method list in CLAUDE.md and DESIGN.md (updated). The `O_EXCL` hit left is tests/test_config.py's docstring about the old behaviour (a record). Dated specs and ROADMAP history untouched.

Gates: `pytest tests/ -q` (527 passed) and `ruff check .` after every commit. Not run: local-ci.sh, ESLint, mypy, djlint, the Python matrix, the shell scripts under CI.
