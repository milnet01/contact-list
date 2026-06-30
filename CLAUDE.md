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
- **No new dependencies** without justification (budget: <8 direct pip packages).
- Type hints on all signatures; PEP 8; line length 100; specific exceptions only.

## Running & testing

```bash
./run.sh                         # create venv, install, launch on :5002
python -m pytest tests/ -v       # run the test suite
```

## Privileged commands

Use `SUDO_ASKPASS=/usr/libexec/ssh/ksshaskpass sudo -A -p "Claude Code: <reason>"`
for anything needing root — never bare `sudo` (see the drive-level CLAUDE.md).
