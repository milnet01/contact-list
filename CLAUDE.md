# Contact List — Project Instructions

A lightweight, self-hosted Flask + SQLite contact manager. Single-user, runs on
localhost only. Public repo: https://github.com/milnet01/contact-list

## Canonical documents

- **[DESIGN.md](DESIGN.md)** — the authoritative spec and standards. Security,
  efficiency, coding, and testing standards live here; all code must comply.
- **[ROADMAP.md](ROADMAP.md)** — forward work and deferred audit/review items.
- **[CHANGELOG.md](CHANGELOG.md)** — release history (Keep a Changelog).

## Architecture (one-liner)

Flask app factory (`app.py`) → blueprints in `routes/` → plain-function data access
in `models.py` → `sqlite3` via `db.py`. Server-rendered Jinja2 templates, vanilla
JS. No ORM. Google import is in `google_sync.py` / `google_auth.py`.

## Non-negotiable conventions (full detail in DESIGN.md)

- **SQL:** parameterized queries only. Never f-strings/`.format()` in SQL.
- **XSS:** rely on Jinja2 autoescaping; `| e` on any manual `Markup()`.
- **CSRF:** signed token validated on every POST/PUT/DELETE.
- **Secrets:** Google credentials/tokens live in `~/.config/contact-list/`, never
  in the repo or database. `.gitignore` enforces this.
- **No new dependencies** without justification. DESIGN.md §3 holds the
  budget and the exception register.
- **Dependencies track latest.** All deps — runtime, dev/CI tools, GitHub
  Actions, Python — stay on their latest stable release, for features and
  security. Holding a version back requires a documented exception in DESIGN.md
  §3 (*Dependency Exceptions & Breakage Register*) recording the breaking version
  and a re-test trigger.
- Type hints on all signatures; PEP 8; specific exceptions only. `ruff`
  enforces the line length set in `pyproject.toml`.

## Running & testing

```bash
./run.sh                         # create venv, install, launch on :5002
python -m pytest tests/ -v       # run the test suite
./local-ci.sh                    # ruff, mypy, djlint, pytest on the FULL Python matrix, plus ESLint (needs Node)
git config core.hooksPath .githooks   # once per clone: run local CI before every push
```

**`./local-ci.sh` must be green before any push**, and `.githooks/pre-push`
enforces it once `core.hooksPath` is set. It runs `scripts/gate.sh`, the step
list `ci.yml` also runs. A matrix Python it cannot obtain is a **failure**, not
a warning. The hook refuses a push while the working tree differs from the
commit being pushed, since it would test the wrong code: commit or stash first.

Every push is secret-scanned first. A documentation-only push (every changed
file a `*.md` or under `docs/`) skips local CI only when the branch's last
GitHub CI run passed; a tag push never skips. `SKIP_LOCAL_CI=1 git push` is the
emergency override, and it skips the gate only, not the secret scan.

### Verifying a launch by hand

- **Wait for the port, never for a duration.** `run.sh` pip-installs on every
  launch, so a fixed `sleep` gives a false negative on a server that was
  starting perfectly. Poll instead:
  `for _ in $(seq 90); do ss -ltn "sport = :$1" | grep -q LISTEN && break; sleep 1; done`
- **Background the server** (`./run.sh &`). A foreground launch never returns,
  so anything written after it on its own line never runs.
- **Intercept the browser-open** rather than letting it spray tabs — and to
  prove a path opens *no* browser, you need it recorded, not merely unobserved.
  Two different mechanisms (`browser.py`): from source it is stdlib
  `webbrowser`, so `BROWSER='/path/to/recorder %s'` catches it; when frozen it
  shells out to `xdg-open`, so put a fake `xdg-open` first on `PATH`.
- **Isolate the home folder AND the database, both** —
  `HOME=<scratch> CONTACT_LIST_DB=<scratch>/x.db`. Photos, the Google token and
  the log live under `~/.config/contact-list/`, and a page that checks Google
  refreshes and rewrites the real token. From source, the default database is
  `contacts.db` next to the code: the user's real contacts. A script that
  builds the app itself asserts `config.Config.DATABASE` is under the scratch
  folder before calling `create_app()`.

## Privileged commands

Use `SUDO_ASKPASS=/usr/libexec/ssh/ksshaskpass sudo -A -p "Claude Code: <reason>"`
for anything needing root — never bare `sudo` (see the drive-level CLAUDE.md).

---

The arguments behind these rules are in
[docs/history/claude-md.md](docs/history/claude-md.md). This file holds what is
true now; that one holds why.
