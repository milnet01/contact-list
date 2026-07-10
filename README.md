# Contact List

A lightweight, self-hosted contact manager. Store, search, and organise people and
companies on your own machine — with optional two-way sync with your Google Contacts.

It runs as a small local web app (open `http://localhost:5002` in your browser). Your
data lives in a single SQLite file on your computer; nothing is sent anywhere except the
Google sync you explicitly trigger.

## Features

- **People and companies** — store names, emails, phones, and free-form notes.
- **Custom fields** — add your own fields (birthday, address, anything) per contact, no
  database changes needed.
- **Fast search & filter** — search by name/email/phone, filter by type or first letter,
  sort, and paginate.
- **Duplicate detection** — scan for and review likely duplicate contacts.
- **CSV export** — download all your contacts.
- **Two-way Google sync** — pull your Google contacts in, and push your local edits
  and new contacts back (newest edit wins on conflicts). Deletions are not pushed.
- **Security-first** — parameterized SQL, CSRF protection, autoescaped templates, and a
  strict Content-Security-Policy. Runs on `localhost` only.
- **Light footprint** — Flask + SQLite, vanilla HTML/CSS/JS, no build step, no ORM, no
  JS framework.

## Requirements

- Python 3.12 or newer
- Linux/macOS (a `run.sh` launcher is provided; Windows users can run `app.py` directly)

## Quick start

```bash
git clone https://github.com/milnet01/contact-list.git
cd contact-list
./run.sh
```

`run.sh` creates a virtual environment, installs dependencies, launches the app, and
opens your browser at `http://localhost:5002`.

### Manual setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Download & run (no Python needed)

Pre-built launchers are attached to each [GitHub Release](https://github.com/milnet01/contact-list/releases). Download the one for your OS — it carries everything it needs; nothing else to install.

- **Linux:** `Contact-List-x86_64.AppImage` — make it executable (`chmod +x`) and double-click (or run it). Opens the app in your browser.
- **Windows:** `Contact-List.exe` — double-click. Windows SmartScreen may warn on an unsigned app: **More info → Run anyway**.
- **macOS (Apple Silicon — M1/M2/M3 or newer):** `Contact-List.dmg` — open it, drag **Contact List** to Applications, then launch. The first time, **right-click → Open** to get past Gatekeeper (the app is unsigned). Intel Macs are not supported by this build.

Your data (contacts, photos, settings) is stored privately under `~/.config/contact-list/`.

**Google sync (optional)** additionally needs your own Google OAuth `credentials.json` placed in `~/.config/contact-list/` — see [Google Contacts sync](#google-contacts-sync-optional). The launcher does not ship Google credentials.

## Configuration

All settings are read from environment variables (with sensible defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | random per run | Flask session signing key. Set this to keep sessions stable across restarts. |
| `CONTACT_LIST_DB` | `contacts.db` next to the app | Path to the SQLite database file. |
| `CONTACT_LIST_PORT` | `5002` | Port the local server listens on. |

The database file (`contacts.db`) is created automatically on first run and is **not**
committed to the repository.

## Google Contacts sync (optional)

Syncing with Google needs your own Google Cloud OAuth credentials — the app never
ships with any:

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and
   enable the **People API**.
2. Create **OAuth 2.0 client credentials** of type **Desktop app** and download the JSON.
3. Save it to `~/.config/contact-list/credentials.json`.
4. Open the app's **Sync** page and connect — a browser window will ask you to
   authorise access.

Your access token is stored at `~/.config/contact-list/token.json` with `0600`
permissions, never in the database or the repository.

**Two-way sync.** The app requests the read-**write** scope (`contacts`) so it can send
your changes back: local edits to synced contacts, and brand-new local contacts (which
become new Google contacts). When both sides changed the same contact since the last
sync, the **newest edit wins**. Deletions are **not** pushed — deleting a contact here
leaves it on Google. If you previously connected with the old read-only permission, the
Sync page will ask you to reconnect to grant read-write access.

## Running the tests

```bash
python -m pytest tests/ -v
```

## Project layout

```
app.py            Flask app factory and entry point
config.py         Environment-based configuration
db.py             SQLite connection management
models.py         Data access layer (plain functions, no ORM)
google_sync.py    Google People API integration
google_auth.py    Standalone OAuth helper
routes/           CRUD and sync routes
templates/        Jinja2 server-rendered views
static/           CSS and minimal JavaScript
migrations/       Sequential SQL schema migrations
tests/            Unit and route tests
DESIGN.md         Full design document and standards
```

See [DESIGN.md](DESIGN.md) for the architecture, data model, and security/efficiency
standards in detail.

## License

[MIT](LICENSE)
