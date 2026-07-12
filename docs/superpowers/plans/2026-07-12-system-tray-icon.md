# System-Tray Icon (CL-0052) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-platform system-tray/menu-bar icon with a right-click Open / Restart / Quit menu, degrading gracefully to today's headless behaviour where no tray exists.

**Architecture:** A new `tray.py` exposes one function `run_tray(server, port)` that owns the main thread and runs the pystray event loop. `launcher.py` is restructured so the Flask/Werkzeug server moves to a stoppable background thread (`werkzeug.serving.make_server(..., threaded=True)` + `serve_forever()` on a non-daemon thread), leaving the main thread free for the tray. Any tray-init failure is caught at the launcher and falls back to joining the server thread (headless). Restart reuses the existing CL-0046 `server_control.schedule('restart')` mechanism unchanged.

**Tech Stack:** Python 3.12+, Flask/Werkzeug, pystray 0.19.x (new dep), Pillow (existing), PyInstaller (packaging), GitHub Actions (release builds).

## Global Constraints

- **Python 3.12+** — floor unchanged.
- **Dependency budget: at or under 8 direct runtime pip packages.** This change adds `pystray` as the 8th (justified like Pillow). No further deps.
- **`pystray>=0.19,<0.20`** in `requirements.txt` (0.x minor is the breaking boundary; 0.19.5 is current).
- **Linux backend is forced to `appindicator`** via `os.environ.setdefault('PYSTRAY_BACKEND', 'appindicator')` set **before** pystray is imported. Never fall back to the menuless `xorg` backend — on tray failure fall back to **headless**, not a degraded icon (INV-5).
- **SQL** stays parameterized; **CSRF/XSS/secrets** rules unchanged (this change touches no routes/templates).
- **Tray image is the committed master `packaging/icon.png`** (git-tracked), NOT the git-ignored generated `packaging/contact-list.png`.
- **`python app.py` stays headless** — the tray lives only in `launcher.py`/`tray.py` (INV-4). Do not import tray from `app.py`.
- **Type hints on all new signatures; PEP 8; line length 100; specific exceptions** (the one deliberate broad `except Exception` is the tray→headless fallback, commented as such).
- Spec of record: `docs/specs/2026-07-12-system-tray-icon.md`. INV-1…5 are in its "Open invariants" section.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `tray.py` | `run_tray(server, port)` + menu-action helpers; owns the pystray loop | **Create** |
| `tests/test_tray.py` | Unit tests for the three menu actions | **Create** |
| `launcher.py` | Restructured `main()`: background server thread + tray on main thread + headless fallback; updated docstring | **Modify** |
| `tests/test_packaging.py` | Rework `test_launcher_binds_loopback`; add fallback test; add `pystray`-in-requirements test | **Modify** |
| `run.sh` | Exec `launcher.py`; drop `xdg-open`; pip-install every launch | **Modify** |
| `requirements.txt` | Add `pystray>=0.19,<0.20` | **Modify** |
| `packaging/contact-list.spec` | Add `packaging/icon.png` to `datas` | **Modify** |
| `packaging/build-linux.sh` / `.github/workflows/release.yml` | apt-install the GI/Ayatana stack; build with a `gi`-capable interpreter | **Modify** |
| `server_control.py` | Docstring launch-path line (run.sh → launcher.py) | **Modify** |
| `DESIGN.md` | §3 budget (3 sites) + pystray block + C-ext note + platform backends; §7.2 carve-out | **Modify** |
| `README.md` | Tray note; fix stale launcher.py/run.sh/app.py lines | **Modify** |
| `CHANGELOG.md` | `[Unreleased]` Added entry | **Modify** |

---

## Task 1: Linux/KDE spike — de-risk the AppImage tray bundling (THROWAWAY, MANUAL GATE)

**This is the single platform-risk gate (spec §10 step 1). Do it first. It produces no committed code — it validates the build recipe used in Task 7. If it cannot be made to work, invoke Plan-B (below) before continuing.**

**Files:** none committed. Scratch work only.

- [ ] **Step 1: Add pystray to a scratch venv and write a 15-line smoke tray**

Create `/tmp/tray_spike.py`:

```python
import os
os.environ.setdefault('PYSTRAY_BACKEND', 'appindicator')
import pystray
from PIL import Image

def on_quit(icon, item):
    icon.stop()

img = Image.open('packaging/icon.png')
menu = pystray.Menu(
    pystray.MenuItem('Open Contact List', lambda i, x: print('open')),
    pystray.MenuItem('Restart', lambda i, x: print('restart')),
    pystray.MenuItem('Quit', on_quit),
)
pystray.Icon('contact-list', img, 'Contact List', menu).run()
```

Run from the repo root with the system python that has `gi`:
```bash
pip install --user pystray  # or into a --system-site-packages venv
PYTHON=/usr/bin/python3 /usr/bin/python3 /tmp/tray_spike.py
```
Expected: an icon appears in the KDE Plasma tray; right-click shows all three items; Quit exits.

- [ ] **Step 2: Build a throwaway AppImage with the GI stack and confirm the tray survives freezing**

Install the build stack into system python3 and build:
```bash
SUDO_ASKPASS=/usr/libexec/ssh/ksshaskpass sudo -A -p "Claude Code: install AppIndicator build stack for tray spike" \
  apt-get install -y gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
  libgirepository-1.0-1 gir1.2-glib-2.0 python3-gi libgtk-3-0 python3-pip
# Point the frozen build at the gi-capable interpreter:
PYTHON=/usr/bin/python3 bash packaging/build-linux.sh
./Contact-List-x86_64.AppImage
```
Expected: the AppImage runs, the tray icon appears in the KDE tray with a working menu, and it works **without** having pip-installed pystray into the frozen bundle's interpreter beyond what the build collected. Confirm "Namespace AppIndicator3 not available" does **not** appear.

- [ ] **Step 3: Record the exact working build recipe**

Write down (in the Task 7 notes / commit message later): which `apt` packages were needed, which interpreter ran PyInstaller, whether `AyatanaAppIndicator3` had to be added to `hiddenimports`, and any `--break-system-packages` flag needed. **This recipe is the input to Task 7.**

- [ ] **Step 4: Decision gate**

If Steps 1–3 succeed → proceed to Task 2 with the recorded recipe.
If the frozen tray cannot be made to work on the runner-equivalent environment → **Plan-B (spec §6.1):** the Linux AppImage ships tray-less (runtime headless fallback becomes the permanent Linux behaviour); Tasks 2–6 still land (tray works on Windows/macOS and from-source on Linux); Task 7 keeps the Linux build as-is and Task 8's CHANGELOG notes "tray on Windows/macOS; Linux AppImage tray pending." Surface this to the user before proceeding.

- [ ] **Step 5: Clean up scratch files** (`rm /tmp/tray_spike.py`). No commit.

---

## Task 2: Add the `pystray` dependency + DESIGN.md budget lockstep

**Files:**
- Modify: `requirements.txt`
- Modify: `DESIGN.md:41`, `DESIGN.md:44-54` (runtime block), `DESIGN.md:56`, `DESIGN.md:62`
- Test: `tests/test_packaging.py` (add one test)

**Interfaces:**
- Produces: `pystray` importable in the venv (needed by Task 3's `tray.py` and its tests).

- [ ] **Step 1: Write the failing test** — add to `tests/test_packaging.py`:

```python
def test_pystray_in_requirements():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'requirements.txt')) as f:
        reqs = f.read()
    assert 'pystray' in reqs
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_packaging.py::test_pystray_in_requirements -v`
Expected: FAIL (`assert 'pystray' in reqs`).

- [ ] **Step 3: Add pystray to `requirements.txt`** — after the `pillow` line in the Runtime block:

```
pillow>=12.0,<13.0
pystray>=0.19,<0.20
```

- [ ] **Step 4: Install it into the venv**

Run: `./venv/bin/pip install -r requirements.txt`
Expected: pystray (+ Pillow already present, python-xlib, six) install cleanly.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_packaging.py::test_pystray_in_requirements -v`
Expected: PASS.

- [ ] **Step 6: Update DESIGN.md §3 budget in all three sites + add the block entry + notes**

Edit `DESIGN.md:41` — change `must stay under **8 packages** (direct).` to `must stay at or under **8 packages** (direct).` and append to that same sentence's clause about Pillow: ` pystray (CL-0052 tray icon) is **pure Python**, so it adds no C-extension pip dependency; its Linux appindicator backend relies on a GI/GTK3 stack that is a build-time bundling artifact carried in the AppImage (§15), not a declared dependency, so the "one authorised exception: Pillow" wording stands.`

In the runtime code block (`DESIGN.md:44-54`), add after `pillow>=12.0,<13.0`:
```
pystray>=0.19,<0.20
```

Edit `DESIGN.md:56` — change `Seven runtime packages (under the 8-direct budget);` to `Eight runtime packages (at the 8-direct budget); pystray provides the CL-0052 system-tray icon — core desktop UX, justified like the Pillow exception (its Linux backend = Ayatana AppIndicator via gi/GTK3 bundled into the AppImage; macOS = pyobjc-framework-Quartz; Windows = nothing extra; python-xlib ships transitively but the xorg backend is never selected).`

Edit `DESIGN.md:62` — change `the < 8 runtime budget is unaffected.` to `the 8-runtime budget is unaffected.`

- [ ] **Step 7: Run the full suite to confirm nothing broke**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt DESIGN.md tests/test_packaging.py
git commit -m "CL-0052: add pystray dependency + DESIGN.md §3 budget bump to 8"
```

---

## Task 3: `tray.py` module + unit tests

**Files:**
- Create: `tray.py`
- Test: `tests/test_tray.py`

**Interfaces:**
- Consumes: `server_control.schedule('restart')` (existing); `resources.resource_path(*parts)` (existing); a `server` object exposing `.shutdown()`.
- Produces: `run_tray(server, port: int) -> None` (blocks on main thread until Quit; raises on tray-init failure). Internal helpers `_open(port)`, `_restart()`, `_quit(icon, server)`, `_load_icon_image()`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_tray.py`:

```python
import tray


def test_open_opens_browser_at_port(monkeypatch):
    opened = {}
    monkeypatch.setattr(tray.webbrowser, 'open', lambda url: opened.setdefault('url', url))
    tray._open(5002)
    assert opened['url'] == 'http://127.0.0.1:5002'


def test_restart_calls_schedule(monkeypatch):
    called = {}
    monkeypatch.setattr(tray.server_control, 'schedule',
                        lambda action: called.setdefault('action', action))
    tray._restart()
    assert called['action'] == 'restart'


def test_quit_shuts_down_then_stops_icon():
    calls = []

    class FakeServer:
        def shutdown(self):
            calls.append('shutdown')

    class FakeIcon:
        def stop(self):
            calls.append('stop')

    tray._quit(FakeIcon(), FakeServer())
    assert calls == ['shutdown', 'stop']  # order matters: unblock serve_forever, then return Icon.run()
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_tray.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'tray'`).

- [ ] **Step 3: Create `tray.py`**

```python
"""System-tray icon with Open / Restart / Quit (CL-0052).

Cross-platform via pystray. On Linux the appindicator backend (SNI over DBus)
is forced by launcher.py before this module is imported — see
docs/specs/2026-07-12-system-tray-icon.md §4.2. The tray owns the MAIN thread;
the web server runs on a background thread whose stoppable handle is passed in.
Any tray-init failure raises so launcher.py can fall back to headless (INV-3).
"""
from __future__ import annotations

import webbrowser

import server_control
from resources import resource_path


def _load_icon_image():
    """Load the committed master icon (packaging/icon.png) via Pillow and let it
    downscale in memory. NOT the git-ignored generated contact-list.png, which is
    absent on a fresh from-source clone (spec §6.2)."""
    from PIL import Image
    return Image.open(resource_path('packaging', 'icon.png'))


def _open(port: int) -> None:
    webbrowser.open(f'http://127.0.0.1:{port}')


def _restart() -> None:
    # Reuse the CL-0046 respawn; on the tray path the 0.4s flush delay is a no-op.
    server_control.schedule('restart')


def _quit(icon, server) -> None:
    server.shutdown()  # unblocks serve_forever() on the server thread
    icon.stop()        # makes run_tray's Icon.run() return on the main thread


def run_tray(server, port: int) -> None:
    """Build the icon and run the pystray event loop ON THE CALLING (main)
    thread — blocks until Quit. Raises on any tray-init failure so the caller can
    fall back to headless."""
    import pystray  # lazy: backend is chosen at import time, after launcher sets PYSTRAY_BACKEND

    menu = pystray.Menu(
        pystray.MenuItem('Open Contact List', lambda icon, item: _open(port)),
        pystray.MenuItem('Restart', lambda icon, item: _restart()),
        pystray.MenuItem('Quit', lambda icon, item: _quit(icon, server)),
    )
    icon = pystray.Icon('contact-list', _load_icon_image(), 'Contact List', menu)
    icon.run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_tray.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Lint/type-check the new module**

Run: `./venv/bin/python -m ruff check tray.py && ./venv/bin/python -m mypy tray.py`
Expected: clean (or only the documented pre-existing project mypy config).

- [ ] **Step 6: Commit**

```bash
git add tray.py tests/test_tray.py
git commit -m "CL-0052: add tray.py (run_tray + Open/Restart/Quit actions) with unit tests"
```

---

## Task 4: `launcher.py` restructure + docstring + DESIGN.md §7.2 carve-out + rework launcher tests

**Files:**
- Modify: `launcher.py:1-10` (docstring), `launcher.py:65-88` (`main()`)
- Modify: `DESIGN.md:310` (§7.2 carve-out)
- Modify: `tests/test_packaging.py` (rework `test_launcher_binds_loopback`; add fallback test)

**Interfaces:**
- Consumes: `tray.run_tray(server, port)` (Task 3); `werkzeug.serving.make_server`; `config.Config.PORT`.
- Produces: `launcher.main()` unchanged signature `() -> int`; returns 0 on clean start/quit or headless fallback, 1 on `create_app()` failure.

- [ ] **Step 1: Rework the failing test** — replace `test_launcher_binds_loopback` in `tests/test_packaging.py` (currently at lines 62-70) with:

```python
def test_launcher_uses_make_server_threaded_loopback(monkeypatch):
    import launcher
    monkeypatch.setattr(launcher, '_port_is_serving', lambda h, p: False)
    monkeypatch.setattr(launcher, '_open_when_ready', lambda port: None)
    monkeypatch.setattr('app.create_app', lambda: object())

    rec = {}

    class FakeServer:
        def serve_forever(self):
            return None

        def shutdown(self):
            pass

    def fake_make_server(host, port, app, **kwargs):
        rec['host'] = host
        rec['threaded'] = kwargs.get('threaded')
        return FakeServer()

    monkeypatch.setattr('werkzeug.serving.make_server', fake_make_server)
    # Tray returns immediately (as if Quit was pressed) → main() reaps the thread.
    monkeypatch.setattr('tray.run_tray', lambda server, port: None)

    assert launcher.main() == 0
    assert rec['host'] == '127.0.0.1'
    assert rec['threaded'] is True  # locks in the anti-serialize guard (spec §5)
```

- [ ] **Step 2: Add the fallback test** — add to `tests/test_packaging.py`:

```python
def test_launcher_falls_back_to_headless_when_tray_fails(monkeypatch):
    import launcher
    monkeypatch.setattr(launcher, '_port_is_serving', lambda h, p: False)
    monkeypatch.setattr(launcher, '_open_when_ready', lambda port: None)
    monkeypatch.setattr('app.create_app', lambda: object())

    class FakeServer:
        def serve_forever(self):
            return None

        def shutdown(self):
            pass

    monkeypatch.setattr('werkzeug.serving.make_server', lambda *a, **k: FakeServer())

    def boom(server, port):
        raise RuntimeError('no tray here')

    monkeypatch.setattr('tray.run_tray', boom)
    # Fallback must not raise and must still return 0 (headless server ran).
    assert launcher.main() == 0
```

- [ ] **Step 3: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -k "make_server or headless" -v`
Expected: FAIL (launcher still calls `app.run()`, no `make_server`/tray wiring yet).

- [ ] **Step 4: Rewrite `launcher.main()`** — replace the body from `from app import create_app` through the final `return 0` (lines 80-88) with:

```python
    # On Linux, pin pystray to the appindicator backend (SNI over DBus) BEFORE
    # tray.py imports pystray (spec §4.2). setdefault honours an explicit user
    # PYSTRAY_BACKEND override.
    os.environ.setdefault('PYSTRAY_BACKEND', 'appindicator')

    from app import create_app
    from werkzeug.serving import make_server
    try:
        app = create_app()
    except Exception:
        logging.exception('Server startup failed')
        return 1

    # The tray must own the main thread, so the server moves to a dedicated
    # non-daemon thread via a stoppable handle. threaded=True preserves app.run()'s
    # default concurrency (make_server defaults threaded=False; spec §5).
    server = make_server('127.0.0.1', port, app, threaded=True)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()

    threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()

    try:
        import tray
        tray.run_tray(server, port)  # blocks on the main thread until Quit
    except Exception:
        # Graceful fallback (INV-3): no tray → behave exactly as before. INFO, not
        # a warning: nobody is worse off. Join the server thread so we live as long
        # as the server does.
        logging.info('system tray unavailable; running without an icon', exc_info=True)
        server_thread.join()
        return 0

    # Quit path: run_tray returned because on_quit called server.shutdown(); reap
    # the now-finished server thread so the port is released (INV-1).
    server_thread.join()
    return 0
```

- [ ] **Step 5: Update the `launcher.py` module docstring** (lines 1-10) to:

```python
"""Entry point for Contact List — used by the frozen (PyInstaller) apps AND the
from-source `./run.sh` (both route through here).

Responsibilities, in order:
 1. If invoked with --google-auth (frozen only), run the OAuth flow and exit.
 2. If the app is already serving on the port, just open the browser and exit.
 3. When frozen, create the config dir and install a file log (no console).
 4. Build the app, start the web server on a background thread, open the browser
    once the socket is up, and run the system-tray icon on the main thread
    (falling back to a headless server join where no tray is available).

app.py is unchanged; `python app.py` from source stays a headless server (no tray).
"""
```

- [ ] **Step 6: Run the launcher tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_packaging.py -v`
Expected: PASS, including the single-instance test (`test_launcher_single_instance_opens_browser`) still green (INV-2).

- [ ] **Step 7: Add the §7.2 carve-out to DESIGN.md** — append to the `- **No background threads...` bullet at `DESIGN.md:310`:

```
 *Exception (CL-0052):* the system-tray icon owns the main thread, so the HTTP server runs on **one dedicated long-lived background thread** for the whole app lifetime — a materially stronger carve-out than the one-shot threads above (serving HTTP *is* application work). No shared mutable app state crosses threads beyond the server socket; Quit calls `server.shutdown()` then `join()`s the thread. See `docs/specs/2026-07-12-system-tray-icon.md` §5.
```

- [ ] **Step 8: Run the full suite**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add launcher.py tests/test_packaging.py DESIGN.md
git commit -m "CL-0052: restructure launcher (tray on main thread, server on bg thread, headless fallback)"
```

---

## Task 5: `run.sh` repoint + `server_control.py` docstring

**Files:**
- Modify: `run.sh`
- Modify: `server_control.py:1-13` (docstring launch-path line)

**Interfaces:**
- Consumes: `launcher.py` `main()` (Task 4).

- [ ] **Step 1: Rewrite `run.sh`** to route through `launcher.py`, drop the double browser-open, and sync deps every launch:

```bash
#!/usr/bin/env bash
# Launch the Contact List app
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/venv"

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Sync dependencies on EVERY launch so a pulled update (e.g. the new pystray dep
# for the tray icon) installs even into an existing venv. Idempotent; a small
# fixed cost (~1-3s) once satisfied.
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# Run the app. launcher.py owns the tray + browser-open; no separate xdg-open here
# (it would open the browser twice).
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" launcher.py
```

- [ ] **Step 2: Verify from source manually**

Run: `./run.sh`
Expected: deps sync, the app starts, the browser opens exactly **once**, and (on a tray-capable desktop) the tray icon appears with Open/Restart/Quit. On a headless/unsupported session it still serves and opens the browser (check the log line "system tray unavailable" in `~/.config/contact-list/contact-list.log` if frozen, or stderr from source). Ctrl-C or Quit to stop.

- [ ] **Step 3: Update `server_control.py` docstring** — change the line at `server_control.py:3` from:

```
The app is launched from a desktop icon (``run.sh`` → ``exec python app.py``,
```
to:
```
The app is launched from a desktop icon (``run.sh`` → ``exec python launcher.py``,
```

- [ ] **Step 4: Run the suite (server_control tests must stay green)**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all pass (the `PYTEST_CURRENT_TEST` guard still prevents any real respawn).

- [ ] **Step 5: Commit**

```bash
git add run.sh server_control.py
git commit -m "CL-0052: repoint run.sh through launcher.py (tray from source; sync deps every launch)"
```

---

## Task 6: PyInstaller spec — bundle the tray icon

**Files:**
- Modify: `packaging/contact-list.spec:16-20` (`datas`)

**Interfaces:**
- Consumes: `resources.resource_path('packaging', 'icon.png')` at runtime (Task 3's `_load_icon_image`).

- [ ] **Step 1: Add the master icon to `datas`** — in `packaging/contact-list.spec`, change the `datas` list to include the icon (ROOT-anchored per the file's own rule at `contact-list.spec:9-13`):

```python
datas = [
    (os.path.join(ROOT, 'templates'), 'templates'),
    (os.path.join(ROOT, 'static'), 'static'),
    (os.path.join(ROOT, 'migrations'), 'migrations'),
    (os.path.join(ROOT, 'packaging', 'icon.png'), 'packaging'),
]
```

- [ ] **Step 2: Verify the icon resolves in a frozen bundle (quick local freeze)**

Run:
```bash
bash packaging/make-icons.sh   # ensures packaging/icon.* exist locally
PYTHON=/usr/bin/python3 pyinstaller --noconfirm packaging/contact-list.spec
python3 -c "import os; print(os.path.exists('dist/Contact-List/_internal/packaging/icon.png') or os.path.exists('dist/Contact-List/packaging/icon.png'))"
```
Expected: prints `True` (the icon landed under `packaging/` in the bundle). Layout path varies by PyInstaller version; either location is fine.

- [ ] **Step 3: Commit**

```bash
git add packaging/contact-list.spec
git commit -m "CL-0052: bundle packaging/icon.png into the PyInstaller datas for the tray"
```

---

## Task 7: CI build — install the GI/Ayatana stack for the Linux release

**Files:**
- Modify: `.github/workflows/release.yml` (the `build-linux` job)

**Use the recipe validated in Task 1.** The block below is the expected default; if the spike found a different working incantation (extra `hiddenimports`, a different interpreter selection), apply that instead.

**Interfaces:** none (CI-only).

- [ ] **Step 1: Replace the `build-linux` job** in `.github/workflows/release.yml` so the build runs under a `gi`-capable interpreter with the Ayatana stack present:

```yaml
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      # appindicator tray needs the Ayatana/GI/GTK stack at build time so
      # PyInstaller can bundle it; desktop-file-utils is for appimagetool. The
      # build runs under /usr/bin/python3 (which has python3-gi) — see spec §6.1.
      - name: Install AppIndicator/GI build stack
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            desktop-file-utils \
            gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
            libgirepository-1.0-1 gir1.2-glib-2.0 python3-gi libgtk-3-0 \
            python3-pip python3-venv
      - run: sudo python3 -m pip install --break-system-packages -r requirements.txt pyinstaller
      - run: PYTHON=/usr/bin/python3 bash packaging/build-linux.sh
      - uses: actions/upload-artifact@v7
        with:
          name: linux
          path: Contact-List-x86_64.AppImage
```

(Windows/macOS jobs are unchanged — pystray needs no GI stack there.)

- [ ] **Step 2: Validate the workflow YAML locally**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: no error (valid YAML).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "CL-0052: install the AppIndicator/GI stack in the Linux release build"
```

---

## Task 8: User-facing docs — README + CHANGELOG

**Files:**
- Modify: `README.md:83`, `README.md:140`, `README.md:141`, and the run/usage section (~line 69-90)
- Modify: `CHANGELOG.md` (`[Unreleased]`)

**Interfaces:** none.

- [ ] **Step 1: Add a tray note to the README run/usage section** — after the "The app opens in your browser automatically" line (~line 69), add:

```markdown
A small **system-tray icon** also appears (a Contact List icon near your clock).
Right-click it for **Open Contact List**, **Restart**, and **Quit** — a persistent
control point that doesn't depend on having the browser tab open. Where a desktop
has no system tray, the app simply runs without the icon.
```

- [ ] **Step 2: Fix the stale `run.sh` description** — change `README.md:83` from:

```
`run.sh` creates a virtual environment, installs dependencies, launches the app, and opens
```
to:
```
`run.sh` creates a virtual environment, installs/updates dependencies on each launch, and starts the app (via `launcher.py`, which opens
```
(adjust the sentence tail so it reads cleanly with the following line — the app opens the browser and shows the tray icon).

- [ ] **Step 3: Fix the stale project-layout lines** — change `README.md:140-141` from:

```
launcher.py       Entry point for the packaged one-file apps (starts server + opens browser)
app.py            Flask app factory and from-source entry point
```
to:
```
launcher.py       Entry point for the packaged apps AND ./run.sh (starts server, opens browser, runs the tray icon)
app.py            Flask app factory; headless server when run directly (python app.py — no tray)
```

- [ ] **Step 4: Add the CHANGELOG entry** — under `## [Unreleased]`, add an `### Added` section:

```markdown
### Added

- **System-tray icon with an Open / Restart / Quit menu (CL-0052).**
  A small icon appears near your clock (Windows, macOS, and Linux). Right-click
  it to open the app in your browser, restart it, or quit — no need to keep the
  browser tab open. Where a desktop has no system tray, the app runs without the
  icon, exactly as before.
```

- [ ] **Step 5: Verify Markdown renders / no broken structure**

Run: `./venv/bin/python -m pytest tests/ -q`
Expected: all pass (docs-only; sanity that nothing imports broke).

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "CL-0052: document the system-tray icon (README + CHANGELOG)"
```

---

## Task 9: Full release-build verification (MANUAL, all three OSes)

**Files:** none.

- [ ] **Step 1: Trigger a rehearsal release build**

Push the branch (or run `workflow_dispatch`) so the release workflow builds all three launchers without publishing (the release job is gated on a `v*` tag). Watch: `gh run watch` or the Actions tab.
Expected: `build-linux`, `build-windows`, `build-macos` all green.

- [ ] **Step 2: Verify the Linux AppImage tray on KDE**

Download the `linux` artifact, run `./Contact-List-x86_64.AppImage`.
Expected: tray icon appears in the KDE tray; Open launches the browser; Restart relaunches (icon disappears then reappears, port re-serves); Quit removes the icon and exits with the port freed (a subsequent launch binds cleanly — INV-1).

- [ ] **Step 3: Verify Windows + macOS tray**

On each, run the artifact and confirm the menu-bar/tray icon shows Open/Restart/Quit and each works.
Expected: all three actions functional; on macOS the icon sits in the menu bar (tray owns the main thread — no AppKit crash).

- [ ] **Step 4: Verify the headless fallback**

Run the AppImage in a session with no tray host (e.g. a bare X session, or `pkill` the tray host), or set `PYSTRAY_BACKEND=nonsense`.
Expected: no icon, but the server runs and the browser opens; the log shows "system tray unavailable; running without an icon".

- [ ] **Step 5: Final commit / roadmap flip**

If all green, mark CL-0052 shipped:
```bash
git commit --allow-empty -m "CL-0052: system-tray icon verified on Linux/Windows/macOS"
```
(Then flip the ROADMAP bullet to shipped and add the CHANGELOG under a release when tagging — outside this plan's scope.)

---

## Self-Review Notes (author checklist — completed)

- **Spec coverage:** §4 backend force → Task 4 Step 4 (`PYSTRAY_BACKEND` setdefault) + Global Constraints; §5 startup restructure → Task 4; §5 run.sh → Task 5; §5 tray.py interface → Task 3; §6.1 build stack → Tasks 1 & 7; §6.2 icon.png datas → Task 6 (+ Task 3 `_load_icon_image`); §7 fallback → Task 4 Step 4 + Task 9 Step 4; §8 deps/docs → Tasks 2, 4 (§7.2), 5 (docstrings), 8 (README/CHANGELOG); §9 tests → Tasks 2, 3, 4; §10 order → task sequence; INV-1…5 → Tasks 4 & 9.
- **Placeholder scan:** none — every code/edit step shows the actual content.
- **Type/name consistency:** `run_tray(server, port)`, `_open`, `_restart`, `_quit`, `_load_icon_image`, `make_server(..., threaded=True)`, `server_control.schedule('restart')`, `resource_path('packaging', 'icon.png')` used identically across tasks.
- **Known deferral:** the exact CI interpreter incantation (Task 7) is validated by the Task 1 spike; Plan-B (Linux tray-less) is defined if it can't be made to work.
