# Standalone One-File Launchers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one self-contained, double-clickable launcher per desktop OS (Linux `.AppImage`, Windows `.exe`, macOS `.dmg`) that carries its own Python + all deps, built by GitHub Actions on a version tag.

**Architecture:** Freeze the existing Flask app with PyInstaller. A new `launcher.py` is the frozen entrypoint (starts the server, opens the browser, dispatches the Google-auth child). Small code changes make the app freeze-safe: mutable state moves to `~/.config/contact-list/` when frozen, bundled resources resolve via a `resource_path()` helper, and Google OAuth re-invokes the binary with `--google-auth`. Packaging scripts live under `packaging/`; a `release.yml` workflow builds all three OSes.

**Tech Stack:** Python 3.12, Flask, PyInstaller (build-time only), appimagetool (Linux), Wine (local Windows pre-flight), `hdiutil`/`iconutil`/`codesign` (macOS, CI-only), GitHub Actions.

**Design spec:** `docs/specs/2026-07-10-standalone-launchers-design.md` (signed off). Read it before starting; this plan implements it verbatim.

## Global Constraints

- **Python floor:** 3.12 (per `requirements.txt` header). Build binaries on 3.12.
- **No new runtime dependency.** PyInstaller/appimagetool/icon tools are build-time only — never added to `requirements.txt` (DESIGN.md §3 budget < 8). `pytest` stays the only dev dep.
- **From-source behaviour must not change.** Every frozen-only branch is gated on `getattr(sys, 'frozen', False)`; running `./run.sh` / `python app.py` behaves exactly as today.
- **Bind loopback only:** `127.0.0.1` (DESIGN.md §6.3). Never `0.0.0.0`.
- **SQL parameterized; CSRF on POST; Jinja2 autoescape** — unchanged; do not touch these paths.
- **Type hints on all new signatures; PEP 8; line length 100; specific exceptions.**
- **Commit style:** `CL-0049: <description>`. Direct to `main` (project convention). Public repo — push after each commit.
- **Icon masters already committed** (`b739943`): `packaging/icon.png` (1254², transparent), `packaging/icon-source.png`, `packaging/old-icon-flatblue.svg`.

---

## File Structure

**New files:**
- `resources.py` — `resource_path()` helper (frozen-aware resource base).
- `launcher.py` — frozen entrypoint (auth dispatch, single-instance, file-logging, server+browser).
- `packaging/contact-list.spec` — shared PyInstaller recipe.
- `packaging/make-icons.sh` — derive `.ico`/`.icns`/PNGs from `packaging/icon.png`.
- `packaging/build-linux.sh` — AppImage build (local + CI).
- `packaging/wine-setup.sh`, `packaging/build-windows.sh` — Wine pre-flight + `.exe`.
- `packaging/build-macos.sh` — `.app` + ad-hoc sign + `.dmg` (CI-only).
- `.github/workflows/release.yml` — 3 build jobs + release job.
- `tests/test_packaging.py` — unit tests for the freeze-safe seams.
- `static/icon.png` — committed favicon (generated once from the master).

**Modified files:**
- `config.py` — frozen-aware `DATABASE` default.
- `db.py` — `migrations_dir` via `resource_path`.
- `app.py` — `Flask(...)` template/static folders via `resource_path`.
- `routes/sync.py` — hoist `auth_script` to module scope + `_auth_command` helper.
- `templates/base.html` — favicon `<link>` → PNG.
- `.gitignore` — ignore `packaging/.tools/`, generated icons.
- `README.md` — download/run section.
- `DESIGN.md` — §3 note, §7.1 note, §7.2 carve-out, new Packaging section.

**Removed:** `static/icon.svg` (retired; replaced by `static/icon.png`).

---

### Task 1: `resource_path` helper + wire into db.py and app.py

Makes bundled templates/static/migrations resolvable when frozen; a no-op change from source.

**Files:**
- Create: `resources.py`
- Modify: `db.py:66`, `app.py:17`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Produces: `resources.resource_path(*parts: str) -> str` — absolute path under `sys._MEIPASS` when frozen, else repo root.

- [ ] **Step 1: Write the failing test**

Create `tests/test_packaging.py`. The env guards go at the very top, **before any
`import config`/`import app`**, so importing the app never writes a `secret_key`
into the real `~/.config/contact-list` and never points at the real DB:

```python
import os
import sys

# Isolation: set BEFORE importing config/app (see §10 of the spec).
os.environ.setdefault('SECRET_KEY', 'test-key-not-persisted')
os.environ.setdefault('CONTACT_LIST_DB', '/tmp/contact-list-test.db')

from resources import resource_path


def test_resource_path_from_source():
    # From source: base is the repo root (resources.py's dir).
    got = resource_path('migrations')
    assert got == os.path.join(os.path.dirname(os.path.abspath(__import__('resources').__file__)), 'migrations')


def test_resource_path_uses_meipass_when_set(monkeypatch):
    monkeypatch.setattr(sys, '_MEIPASS', '/tmp/frozen', raising=False)
    assert resource_path('templates') == os.path.join('/tmp/frozen', 'templates')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resources'`.

- [ ] **Step 3: Create `resources.py`**

```python
"""Resolve bundled read-only resources in both source and frozen (PyInstaller)
runs. Frozen apps unpack data under ``sys._MEIPASS``; from source the base is this
file's directory (the repo root)."""
from __future__ import annotations

import os
import sys


def resource_path(*parts: str) -> str:
    """Absolute path to a bundled resource (templates/static/migrations)."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)
```

- [ ] **Step 4: Wire into `db.py`**

At the top of `db.py` add `from resources import resource_path`. Change line 66 from:

```python
    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')
```

to:

```python
    migrations_dir = resource_path('migrations')
```

- [ ] **Step 5: Wire into `app.py`**

At the top of `app.py` add `from resources import resource_path`. Change line 17 from:

```python
    app = Flask(__name__)
```

to:

```python
    app = Flask(
        __name__,
        template_folder=resource_path('templates'),
        static_folder=resource_path('static'),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -v && ./venv/bin/python -m pytest tests/ -q`
Expected: new tests PASS; full suite still green (resource_path returns the same paths from source, so app/db behaviour is unchanged).

- [ ] **Step 7: Commit**

```bash
git add resources.py db.py app.py tests/test_packaging.py
git commit -m "CL-0049: resource_path helper for freeze-safe templates/static/migrations"
git push origin main
```

---

### Task 2: Frozen-aware database path in `config.py`

When frozen, put `contacts.db` in the persistent config dir (so it isn't wiped on quit). From source, unchanged.

**Files:**
- Modify: `config.py` (add `import sys`, `_default_db_path()`, change `DATABASE`)
- Test: `tests/test_packaging.py`

**Interfaces:**
- Produces: `config._default_db_path() -> str` — reads `sys.frozen` live on each call.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
import config


def test_default_db_path_from_source():
    assert config._default_db_path().endswith('contacts.db')
    # From source it is next to the code, NOT under ~/.config.
    assert '.config/contact-list' not in config._default_db_path()


def test_default_db_path_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    got = config._default_db_path()
    assert got == os.path.join(config._CONFIG_DIR, 'contacts.db')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k default_db_path -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute '_default_db_path'`.

- [ ] **Step 3: Edit `config.py`**

Add `import sys` to the imports at the top. Replace the current `DATABASE` assignment (config.py:72-75):

```python
    DATABASE = os.environ.get(
        'CONTACT_LIST_DB',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db'),
    )
```

with a module-level helper above `class Config` and a one-line default inside it:

```python
def _default_db_path() -> str:
    """Default DB location. Frozen: the persistent config dir (so contacts survive
    quit). From source: next to the code, unchanged. Reads sys.frozen on each call
    so tests can monkeypatch it; Config.DATABASE binds the result at import."""
    if getattr(sys, 'frozen', False):
        return os.path.join(_CONFIG_DIR, 'contacts.db')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db')


class Config:
    SECRET_KEY = _load_or_create_secret_key()
    DATABASE = os.environ.get('CONTACT_LIST_DB', _default_db_path())
```

(Keep the rest of `class Config` exactly as-is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k default_db_path -v && ./venv/bin/python -m pytest tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_packaging.py
git commit -m "CL-0049: frozen-aware DATABASE default (persistent config dir when bundled)"
git push origin main
```

---

### Task 3: Frozen-aware Google auth dispatch in `routes/sync.py`

Frozen binaries have no `python`/`.py` file to spawn, so the auth flow re-invokes the binary with `--google-auth`. Extract the argv choice into a plain, testable helper.

**Files:**
- Modify: `routes/sync.py` (hoist `auth_script` to module scope; add `_auth_command`; call it)
- Test: `tests/test_packaging.py`

**Interfaces:**
- Produces: `routes.sync._auth_command(frozen: bool) -> list[str]`.
- Consumes (Task 4): `launcher.main` handles `--google-auth` by calling `google_auth.main()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
from routes import sync as sync_module


def test_auth_command_from_source():
    cmd = sync_module._auth_command(False)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith('google_auth.py')


def test_auth_command_when_frozen():
    assert sync_module._auth_command(True) == [sys.executable, '--google-auth']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k auth_command -v`
Expected: FAIL — `AttributeError: ... has no attribute '_auth_command'`.

- [ ] **Step 3: Edit `routes/sync.py`**

Ensure `import sys` is present at the top. Add a module-level constant (near the other imports) and helper:

```python
# Absolute path to the standalone auth script, used from source. Module-level so
# both authorize() and _auth_command reference the same value.
auth_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'google_auth.py')


def _auth_command(frozen: bool) -> list[str]:
    """argv for the Google-auth child. Frozen: re-invoke this binary with the flag
    (launcher.py routes it to google_auth.main()). From source: run the .py."""
    if frozen:
        return [sys.executable, '--google-auth']
    return [sys.executable, auth_script]
```

In `authorize()` (routes/sync.py:50-56), delete the local `auth_script = ...` line and replace the `subprocess.run` call's command:

```python
    # Use InstalledAppFlow via the standalone auth script (or this binary, frozen)
    cmd = _auth_command(getattr(sys, 'frozen', False))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
        )
```

(Everything below the `subprocess.run` call is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k auth_command -v && ./venv/bin/python -m pytest tests/ -q`
Expected: PASS; full suite green (the source path still spawns `python google_auth.py`).

- [ ] **Step 5: Commit**

```bash
git add routes/sync.py tests/test_packaging.py
git commit -m "CL-0049: frozen-aware Google auth child command (_auth_command helper)"
git push origin main
```

---

### Task 4: `launcher.py` frozen entrypoint

Starts the server, opens the browser, dispatches the auth child, and — when frozen — logs to a file and creates the config dir first.

**Files:**
- Create: `launcher.py`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `config.Config.PORT`, `config._CONFIG_DIR`, `config.ensure_private_dir`, `app.create_app`, `google_auth.main`, `routes.sync._auth_command` (indirectly, via `--google-auth`).
- Produces: `launcher.main() -> int`; helpers `_port_is_serving(host, port)`, `_open_when_ready(port)`, `_install_file_logging()`.

- [ ] **Step 1: Write the failing tests (isolation-safe)**

Append to `tests/test_packaging.py`. The `SECRET_KEY`/`CONTACT_LIST_DB` guards from Task 1 (top of the file) keep these out of real state; each test also patches `create_app` so the real `init_db` never runs:

```python
import types


def test_launcher_single_instance_opens_browser(monkeypatch):
    import launcher
    opened = {}
    monkeypatch.setattr(launcher, '_port_is_serving', lambda h, p: True)
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda url: opened.setdefault('url', url))
    # If create_app is reached, fail — the already-serving path must short-circuit.
    monkeypatch.setattr('app.create_app', lambda: (_ for _ in ()).throw(AssertionError('should not build app')))
    assert launcher.main() == 0
    assert opened['url'].endswith(':5002')


def test_launcher_binds_loopback(monkeypatch):
    import launcher
    monkeypatch.setattr(launcher, '_port_is_serving', lambda h, p: False)
    monkeypatch.setattr(launcher, '_open_when_ready', lambda port: None)
    dummy = types.SimpleNamespace(run=lambda **kw: rec.update(kw))
    rec = {}
    monkeypatch.setattr('app.create_app', lambda: dummy)
    assert launcher.main() == 0
    assert rec['host'] == '127.0.0.1'
```

(The `SECRET_KEY`/`CONTACT_LIST_DB` env guards were already placed at the top of the file in Task 1 — do not duplicate them.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k launcher -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'launcher'`.

- [ ] **Step 3: Create `launcher.py`**

```python
"""Frozen (PyInstaller) entrypoint for Contact List.

Responsibilities, in order:
 1. If invoked with --google-auth (frozen only), run the OAuth flow and exit.
 2. If the app is already serving on the port, just open the browser and exit.
 3. When frozen, create the config dir and install a file log (no console).
 4. Build the app, open the browser once the socket is up, run the server.

app.py is unchanged; `python app.py` from source still works as before.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser

_OPEN_DEADLINE_S = 15.0


def _port_is_serving(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _open_when_ready(port: int) -> None:
    """Poll the loopback port and open the browser once it accepts a connection.
    Bounded so a server that never binds doesn't spin the thread forever."""
    start = time.monotonic()
    while time.monotonic() - start < _OPEN_DEADLINE_S:
        if _port_is_serving('127.0.0.1', port):
            webbrowser.open(f'http://127.0.0.1:{port}')
            return
        time.sleep(0.1)


def _install_file_logging() -> None:
    """Frozen-only: ensure the 0700 config dir exists, then log to a file there.
    Runs before create_app(), so it also guarantees the dir for the frozen DB.
    Sets the root level/formatter itself (app.py's basicConfig is a no-op once a
    handler exists)."""
    from config import _CONFIG_DIR, ensure_private_dir
    ensure_private_dir(_CONFIG_DIR)
    handler = logging.FileHandler(os.path.join(_CONFIG_DIR, 'contact-list.log'))
    handler.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> int:
    if getattr(sys, 'frozen', False) and '--google-auth' in sys.argv:
        from google_auth import main as auth_main
        return auth_main()

    from config import Config
    port = Config.PORT

    if _port_is_serving('127.0.0.1', port):
        webbrowser.open(f'http://127.0.0.1:{port}')
        return 0

    if getattr(sys, 'frozen', False):
        _install_file_logging()

    from app import create_app
    try:
        app = create_app()
        threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
        app.run(host='127.0.0.1', port=port, debug=False)
    except Exception:
        logging.exception('Server startup failed')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k launcher -v && ./venv/bin/python -m pytest tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Smoke-test the launcher from source**

Run: `CONTACT_LIST_PORT=5099 ./venv/bin/python launcher.py &` then `sleep 2 && curl -s http://127.0.0.1:5099/ | head -1 && kill %1`
Expected: HTML returned (the contact list page). The browser may open — that's fine.

- [ ] **Step 6: Commit**

```bash
git add launcher.py tests/test_packaging.py
git commit -m "CL-0049: launcher.py frozen entrypoint (server + browser + auth dispatch + file log)"
git push origin main
```

---

### Task 5: Favicon swap (new PNG, retire the SVG)

Replace the old flat-blue `static/icon.svg` favicon with a PNG rendered from the new master, so the browser tab matches the launcher.

**Files:**
- Create: `static/icon.png` (committed)
- Modify: `templates/base.html:7`
- Remove: `static/icon.svg`

- [ ] **Step 1: Generate the committed favicon PNG**

Run:

```bash
./venv/bin/python -c "from PIL import Image; Image.open('packaging/icon.png').resize((64,64), Image.LANCZOS).save('static/icon.png')"
```

Expected: `static/icon.png` created (64×64).

- [ ] **Step 2: Repoint the favicon link**

In `templates/base.html:7`, change:

```html
    <link rel="icon" href="{{ url_for('static', filename='icon.svg') }}" type="image/svg+xml">
```

to:

```html
    <link rel="icon" href="{{ url_for('static', filename='icon.png') }}" type="image/png">
```

- [ ] **Step 3: Retire the old SVG**

Run: `git rm static/icon.svg`
(The retired art is preserved for provenance at `packaging/old-icon-flatblue.svg`, already committed.)

- [ ] **Step 4: Verify no dangling reference**

Run: `./venv/bin/python -m pytest tests/ -q && grep -rn "icon.svg" templates/ static/ app.py routes/ || echo "no icon.svg references"`
Expected: suite green; grep prints "no icon.svg references".

- [ ] **Step 5: Commit**

```bash
git add static/icon.png templates/base.html
git commit -m "CL-0049: swap browser-tab favicon to the new PNG, retire flat-blue SVG"
git push origin main
```

---

### Task 6: Icon derivation script + PyInstaller spec + Linux AppImage build

First buildable artifact. After this task you can build and launch the Linux `.AppImage` locally — the milestone that de-risks all three OS builds.

**Files:**
- Create: `packaging/make-icons.sh`, `packaging/contact-list.spec`, `packaging/build-linux.sh`
- Modify: `.gitignore`

- [ ] **Step 1: Create `packaging/make-icons.sh`**

```bash
#!/usr/bin/env bash
# Derive per-OS icon formats from packaging/icon.png. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
# Resolve an interpreter across Linux (venv), CI (python3), Windows Git-Bash (python).
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in ./venv/bin/python python3 python; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi

"$PY" - <<'PY'
from PIL import Image
m = Image.open('packaging/icon.png')
# Windows multi-size .ico
m.save('packaging/icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
# Linux AppImage 256px
m.resize((256, 256), Image.LANCZOS).save('packaging/contact-list.png')
PY

# macOS .icns (Darwin only; iconutil is macOS-only)
if [ "$(uname)" = "Darwin" ]; then
  ICONSET="packaging/icon.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    "$PY" -c "from PIL import Image; Image.open('packaging/icon.png').resize(($s,$s), Image.LANCZOS).save('$ICONSET/icon_${s}x${s}.png')"
    d=$((s * 2))
    "$PY" -c "from PIL import Image; Image.open('packaging/icon.png').resize(($d,$d), Image.LANCZOS).save('$ICONSET/icon_${s}x${s}@2x.png')"
  done
  iconutil -c icns "$ICONSET" -o packaging/icon.icns
  rm -rf "$ICONSET"
fi
echo "icons generated"
```

Run: `chmod +x packaging/make-icons.sh && ./packaging/make-icons.sh && ls -la packaging/icon.ico packaging/contact-list.png`
Expected: `icon.ico` and `contact-list.png` created.

- [ ] **Step 2: Create `packaging/contact-list.spec`**

```python
# PyInstaller recipe shared by all three OS builds.
# Run from the repo root: pyinstaller packaging/contact-list.spec
# onefile on Windows (single .exe); onedir elsewhere (wrapped by AppImage/.app).
import sys

from PyInstaller.utils.hooks import collect_all

datas = [('templates', 'templates'), ('static', 'static'), ('migrations', 'migrations')]
binaries = []
hiddenimports = []

# These load submodules dynamically and/or ship package data the import scan
# misses; collect_all gathers modules + data + dylibs. Finalise empirically:
# if a frozen run raises ModuleNotFoundError / missing-data, add the package here.
for _pkg in ('googleapiclient', 'google_auth_oauthlib', 'google.auth',
             'google_auth_httplib2', 'phonenumbers'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['pytest'],
)
pyz = PYZ(a.pure)

if sys.platform.startswith('win'):
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name='Contact-List', console=False, icon='packaging/icon.ico',
    )
else:
    _icon = 'packaging/icon.icns' if sys.platform == 'darwin' else 'packaging/contact-list.png'
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name='Contact-List', console=False, icon=_icon,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name='Contact-List')
    if sys.platform == 'darwin':
        app = BUNDLE(
            coll, name='Contact List.app',
            icon='packaging/icon.icns', bundle_identifier='com.contactlist.app',
        )
```

- [ ] **Step 3: Create `packaging/build-linux.sh`**

```bash
#!/usr/bin/env bash
# Build the Linux AppImage. Local pre-flight AND the exact steps CI runs.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in ./venv/bin/python python3 python; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi

TOOLS="packaging/.tools"
APPIMAGETOOL="$TOOLS/appimagetool-x86_64.AppImage"
# Pin a specific release + checksum so a moved/altered download fails loudly.
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="__FILL_AT_IMPLEMENTATION__"   # obtain once: sha256sum the download, paste here

mkdir -p "$TOOLS"
if [ ! -f "$APPIMAGETOOL" ]; then
  curl -fsSL "$APPIMAGETOOL_URL" -o "$APPIMAGETOOL"
  echo "${APPIMAGETOOL_SHA256}  ${APPIMAGETOOL}" | sha256sum -c -
  chmod +x "$APPIMAGETOOL"
fi

bash packaging/make-icons.sh
"$PY" -m PyInstaller --noconfirm packaging/contact-list.spec

APPDIR="build/AppDir"
rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/bin"
cp -r dist/Contact-List/* "$APPDIR/usr/bin/"
cp packaging/contact-list.png "$APPDIR/contact-list.png"

cat > "$APPDIR/contact-list.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Contact List
Exec=Contact-List
Icon=contact-list
Categories=Office;
DESK

cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Contact-List" "$@"
RUN
chmod +x "$APPDIR/AppRun"

ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" Contact-List-x86_64.AppImage
echo "built: Contact-List-x86_64.AppImage"
```

- [ ] **Step 4: Pin the appimagetool checksum**

Run: `curl -fsSL https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage -o /tmp/ait && sha256sum /tmp/ait`
Then paste the hash into `APPIMAGETOOL_SHA256` in `build-linux.sh` (replacing `__FILL_AT_IMPLEMENTATION__`).
Expected: a 64-hex-char checksum recorded in the script.

- [ ] **Step 5: Add build artefacts to `.gitignore`**

Append to `.gitignore`:

```
packaging/.tools/
packaging/icon.ico
packaging/icon.icns
packaging/contact-list.png
```

(`dist/` and `build/` are already ignored.)

- [ ] **Step 6: Install PyInstaller and build the AppImage**

Run:

```bash
./venv/bin/pip install pyinstaller
chmod +x packaging/build-linux.sh
./packaging/build-linux.sh
ls -la Contact-List-x86_64.AppImage
```

Expected: `Contact-List-x86_64.AppImage` produced (tens of MB). If PyInstaller reports a missing module at first launch (Step 7), add it to the `collect_all` loop in `contact-list.spec` and rebuild.

- [ ] **Step 7: Verify the AppImage end-to-end (persistence is the key check)**

Run:

```bash
# Fresh env: move the source DB aside so we prove the frozen app uses ~/.config.
CONTACT_LIST_PORT=5098 ./Contact-List-x86_64.AppImage &
sleep 3
curl -s http://127.0.0.1:5098/ | grep -qi "contact" && echo "SERVING OK"
# Add a contact via the API-less form path is manual; instead check the DB landed in ~/.config:
ls -la ~/.config/contact-list/contacts.db && echo "DB IN CONFIG DIR OK"
kill %1
```

Expected: "SERVING OK" and "DB IN CONFIG DIR OK" (proves §2.1 — the frozen DB lives in the persistent dir, not the temp bundle). Optionally open `http://127.0.0.1:5098` in a browser, add a contact, quit the AppImage, relaunch, and confirm the contact persists.

- [ ] **Step 8: Commit**

```bash
git add packaging/make-icons.sh packaging/contact-list.spec packaging/build-linux.sh .gitignore
git commit -m "CL-0049: PyInstaller spec + make-icons + Linux AppImage build (local pre-flight)"
git push origin main
```

---

### Task 7: Windows `.exe` via Wine (local pre-flight)

Build a real Windows `.exe` on Linux under Wine, to catch packaging errors before CI. The shipped `.exe` is still built on the native Windows runner (Task 9).

**Files:**
- Create: `packaging/wine-setup.sh`, `packaging/build-windows.sh`

- [ ] **Step 1: Create `packaging/wine-setup.sh`**

```bash
#!/usr/bin/env bash
# One-time: install a Windows Python 3.12 into the Wine prefix and the deps.
set -euo pipefail
cd "$(dirname "$0")/.."
PYVER="3.12.7"
INST="python-${PYVER}-amd64.exe"
TOOLS="packaging/.tools"
mkdir -p "$TOOLS"
[ -f "$TOOLS/$INST" ] || curl -fsSL "https://www.python.org/ftp/python/${PYVER}/${INST}" -o "$TOOLS/$INST"
wine "$TOOLS/$INST" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
wine python -m pip install --upgrade pip
wine python -m pip install -r requirements.txt pyinstaller
echo "wine python + deps ready"
```

- [ ] **Step 2: Create `packaging/build-windows.sh`**

```bash
#!/usr/bin/env bash
# Build Contact-List.exe under Wine. Icons are generated natively (Pillow on the
# Linux side) so only PyInstaller runs under Wine.
set -euo pipefail
cd "$(dirname "$0")/.."
bash packaging/make-icons.sh                       # native: produces packaging/icon.ico
wine python -m PyInstaller --noconfirm packaging/contact-list.spec
ls -la dist/Contact-List.exe
echo "built: dist/Contact-List.exe (onefile, under Wine)"
```

- [ ] **Step 3: Run the one-time Wine setup**

Run: `chmod +x packaging/wine-setup.sh packaging/build-windows.sh && ./packaging/wine-setup.sh`
Expected: `wine python --version` works (Python 3.12.x). If the silent installer stalls, run it once interactively (`wine packaging/.tools/python-3.12.7-amd64.exe`).

- [ ] **Step 4: Build and smoke-test the .exe under Wine**

Run:

```bash
./packaging/build-windows.sh
CONTACT_LIST_PORT=5097 wine dist/Contact-List.exe &
sleep 5
curl -s http://127.0.0.1:5097/ | grep -qi "contact" && echo "WINE EXE SERVING OK"
kill %1 2>/dev/null || true
```

Expected: "WINE EXE SERVING OK". (The browser may not open under Wine — the server responding is the pass condition.) Add any missing module to `contact-list.spec`'s `collect_all` loop if a `ModuleNotFoundError` appears in the Wine console.

- [ ] **Step 5: Commit**

```bash
git add packaging/wine-setup.sh packaging/build-windows.sh
git commit -m "CL-0049: Windows .exe build under Wine (local pre-flight)"
git push origin main
```

---

### Task 8: macOS `.dmg` build script (CI-only)

Cannot be built or tested on Linux (no legal macOS container). Write the script; it is exercised only on the macOS CI runner (Task 9).

**Files:**
- Create: `packaging/build-macos.sh`

- [ ] **Step 1: Create `packaging/build-macos.sh`**

```bash
#!/usr/bin/env bash
# macOS ONLY (CI runner). Build the .app, ad-hoc sign it (required to run on
# Apple Silicon), and wrap it in a .dmg with an Applications shortcut.
set -euo pipefail
cd "$(dirname "$0")/.."
bash packaging/make-icons.sh                        # produces packaging/icon.icns on Darwin
python3 -m PyInstaller --noconfirm packaging/contact-list.spec

APP="dist/Contact List.app"
codesign --force --sign - "$APP"                    # ad-hoc; NOT notarization

STAGE="build/dmg"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Contact List" -srcfolder "$STAGE" -format UDZO -ov Contact-List.dmg
echo "built: Contact-List.dmg"
```

- [ ] **Step 2: Lint the script (no macOS to run it here)**

Run: `bash -n packaging/build-macos.sh && chmod +x packaging/build-macos.sh && echo "syntax OK"`
Expected: "syntax OK". (Functional verification happens in the CI dry-run, Task 9 Step 4.)

- [ ] **Step 3: Commit**

```bash
git add packaging/build-macos.sh
git commit -m "CL-0049: macOS .app + ad-hoc sign + .dmg build script (CI-only)"
git push origin main
```

---

### Task 9: GitHub Actions release workflow

Build all three OSes on GitHub's runners; attach to a Release on a `v*` tag, or produce throwaway artifacts via a manual dry-run.

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: Release binaries

on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Build all three without creating a Release'
        type: boolean
        default: true

jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt pyinstaller
      - run: bash packaging/build-linux.sh
      - uses: actions/upload-artifact@v4
        with:
          name: linux
          path: Contact-List-x86_64.AppImage

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt pyinstaller
      - run: bash packaging/make-icons.sh
      - run: pyinstaller --noconfirm packaging/contact-list.spec
      - uses: actions/upload-artifact@v4
        with:
          name: windows
          path: dist/Contact-List.exe

  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt pyinstaller
      - run: bash packaging/build-macos.sh
      - uses: actions/upload-artifact@v4
        with:
          name: macos
          path: Contact-List.dmg

  release:
    needs: [build-linux, build-windows, build-macos]
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/')
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v4
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            linux/Contact-List-x86_64.AppImage
            windows/Contact-List.exe
            macos/Contact-List.dmg
```

Note: the Windows job runs PyInstaller directly (not `build-windows.sh`, which is Wine-specific); `make-icons.sh` runs under Git-Bash on the Windows runner. Confirm the action major versions (`upload-artifact`, `download-artifact`, `action-gh-release`) are current at implementation time (global rule 5a).

- [ ] **Step 2: Validate the workflow YAML**

Run: `./venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo "YAML OK"`
Expected: "YAML OK".

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/release.yml
git commit -m "CL-0049: release workflow — build AppImage/.exe/.dmg on GitHub runners"
git push origin main
```

- [ ] **Step 4: Trigger a dry-run and verify all three build**

Run: `gh workflow run "Release binaries" -f dry_run=true` then `gh run watch`
Expected: all three build jobs green; three artifacts (`linux`, `windows`, `macos`) downloadable from the run. Download and confirm the `.dmg`/`.exe`/`.AppImage` exist. Fix any per-OS failure (usually a missing module → add to `contact-list.spec`) before proceeding.

---

### Task 10: README download section + DESIGN.md updates

Document the download/run steps and record the packaging security stance in the spec of record.

**Files:**
- Modify: `README.md`, `DESIGN.md`

- [ ] **Step 1: Add a README download section**

Insert after the `## Quick start` section in `README.md`:

```markdown
## Download & run (no Python needed)

Pre-built launchers are attached to each [GitHub Release](https://github.com/milnet01/contact-list/releases). Download the one for your OS — it carries everything it needs; nothing else to install.

- **Linux:** `Contact-List-x86_64.AppImage` — make it executable (`chmod +x`) and double-click (or run it). Opens the app in your browser.
- **Windows:** `Contact-List.exe` — double-click. Windows SmartScreen may warn on an unsigned app: **More info → Run anyway**.
- **macOS:** `Contact-List.dmg` — open it, drag **Contact List** to Applications, then launch. The first time, **right-click → Open** to get past Gatekeeper (the app is unsigned).

Your data (contacts, photos, settings) is stored privately under `~/.config/contact-list/`.

**Google sync (optional)** additionally needs your own Google OAuth `credentials.json` placed in `~/.config/contact-list/` — see [Google Contacts sync](#google-contacts-sync-optional). The launcher does not ship Google credentials.
```

- [ ] **Step 2: Update DESIGN.md**

Make these four edits in `DESIGN.md`:
1. **§3 (Dependency budget):** add one line — "PyInstaller, appimagetool, and the OS icon tools are build-time only, not runtime deps; the < 8 runtime budget is unaffected."
2. **§7.1 (Cold start):** add — "The `< 500 ms` target is a source-mode figure; the frozen launchers' first-launch unpack (notably Windows onefile, ~1–2 s) is exempt."
3. **§7.2 (No background threads):** extend the CL-0046 carve-out — "and the launcher's one-shot browser-open daemon thread (opens the browser once after the socket is up; no application work)."
4. **New section "Packaging & distribution":** record the frozen-vs-source resource model, the `~/.config/contact-list` state location when frozen, the per-OS formats, the unsigned/ad-hoc-signed posture (macOS Gatekeeper, Windows SmartScreen), and that the 0700 config-dir lock is POSIX-only (Windows isolation relies on user-profile ACLs).

- [ ] **Step 3: Add a CHANGELOG entry**

Add under `## [Unreleased]` → `### Added` in `CHANGELOG.md`:

```markdown
- **Standalone one-file launchers for Linux, Windows, and macOS.** (CL-0049)
  Download a single file per OS from the GitHub Releases page and run it —
  no Python or dependencies to install. Built automatically by GitHub Actions.
```

- [ ] **Step 4: Verify docs**

Run: `./venv/bin/python -m pytest tests/ -q && grep -n "Packaging & distribution" DESIGN.md && grep -n "Download & run" README.md`
Expected: suite green; both grep hits present.

- [ ] **Step 5: Commit**

```bash
git add README.md DESIGN.md CHANGELOG.md
git commit -m "CL-0049: document launchers (README download section, DESIGN packaging, CHANGELOG)"
git push origin main
```

- [ ] **Step 6: Flip the roadmap item**

Run: the roadmap flip is done via the ants MCP (`roadmap_log` op `flip` id `CL-0049` to_status `shipped`) with a resolution note pointing at the merged work — or by hand-editing `ROADMAP.md` if the MCP is unavailable.

---

## Post-plan: cutting the first real release (follow-on, not part of this plan)

Once the launchers verify (dry-run green + a local AppImage that persists data), tag the release: decide whether the current `[Unreleased]` items publish as the actual first `1.0.0` (the CHANGELOG `[1.0.0]` section exists but was never tagged) or as `1.1.0`, reconcile CL-0050 (the "Initial public release" wording), then `git tag vX.Y.Z && git push --tags` to trigger the Release build.
