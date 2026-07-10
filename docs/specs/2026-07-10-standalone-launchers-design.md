# Standalone one-file launchers for Linux / Windows / macOS (CL-0049)

**Status:** Draft — pending `/cold-eyes` (per global rule 14, this design is run
through the cold-eyes loop until clean before implementation).

## 1. Problem & overview

Today the app has **no published release for any OS** — no git tag, no GitHub
Release, and no downloadable binary. (The CHANGELOG does carry a
`[1.0.0] - 2026-06-30` section, but it was never tagged or published; the
`[Unreleased]` items above it are the work since.) The only way to run it is to
clone the repo and run `./run.sh`, which builds a `venv` and needs a working
Python 3.12+ toolchain on the machine. That is fine for the developer, unusable
for anyone else.

This change produces **one self-contained, double-clickable launcher file per
desktop OS**, each carrying its own Python and every dependency so the end user
installs nothing:

| OS | Shipped file | Launch behaviour |
|----|--------------|------------------|
| Linux | `Contact-List-x86_64.AppImage` | One file, double-click → server starts, browser opens. |
| Windows | `Contact-List.exe` | One file, double-click → server starts, browser opens. No console window. |
| macOS (Apple Silicon) | `Contact-List.dmg` | Disk image → drag app to Applications → launch → browser opens. |

On first run each launcher creates whatever it needs (database, photos folder,
config) under the user's home directory — nothing is written next to the
executable.

**Packaging tool: PyInstaller.** It is the mature standard for freezing a Python
app into a single self-contained artefact, supports all three target OSes, and
handles this app's one native-code dependency (Pillow). Alternatives (Nuitka,
Briefcase) are either fussier or aimed at app-store submission; PyInstaller maps
directly onto the "one file, no install" requirement. It is a **build-time tool
only** — it is never added to `requirements.txt`, so the DESIGN.md §3 runtime
dependency budget (<8 direct packages) is untouched (§7, INV-5).

**Hard constraint — no cross-building.** PyInstaller cannot build a Windows or
macOS binary from Linux; each OS's file must be produced on that OS. This dictates
the build strategy (§6): GitHub Actions' free Windows / macOS / Linux runners
produce the official files, with local pre-flight builds on the dev machine
(native Linux + Windows-under-Wine) to catch packaging errors cheaply before
spending CI on a release.

The app remains what it is: a single-user, `127.0.0.1`-only Flask app
(DESIGN.md §6.3). Packaging adds **no** network exposure (§7, INV-6).

## 2. Making the app safe to freeze

A frozen PyInstaller app resolves its bundled files under `sys._MEIPASS`. In
**onefile** mode (our Windows build, §4.1) that is a per-launch temp directory
**deleted when the process exits**; in **onedir** mode (Linux/macOS, §4.1) it is
the persistent bundle directory — but that is read-only or replaced on reinstall
(e.g. inside a macOS `.app`), so writing user data there is wrong regardless.
Either way, three places in the current code assume "files live next to the
source" and break when frozen. All three key off the frozen state
(`getattr(sys, 'frozen', False)` — or `sys._MEIPASS` for the resource-path helper,
§2.2) so **running from source is completely unchanged** — the new behaviour only
activates inside a bundle.

### 2.1 Where mutable state lives (config.py)

`config.py:74` currently defaults the database to
`os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db')` — next
to the code. Frozen, `__file__` resolves inside `_MEIPASS`: a per-launch temp dir
in onefile mode (contacts wiped on every quit) or a read-only/replaceable bundle
dir in onedir mode (the write fails, or vanishes on reinstall). Either way the DB
must not live there.

Fix: when frozen (and no explicit `CONTACT_LIST_DB` override), default the
database into the **existing** private config dir, alongside the Google token,
`secret_key`, and photos that already live there:

```python
# config.py
import sys

def _default_db_path() -> str:
    # Reads sys.frozen on each call. Config.DATABASE binds the result at import
    # time (as the existing code does), so the §10 test calls this helper
    # DIRECTLY — monkeypatching sys.frozen then re-reading Config.DATABASE would
    # see the stale import-time value.
    if getattr(sys, 'frozen', False):
        return os.path.join(_CONFIG_DIR, 'contacts.db')
    # From source: unchanged — next to the code.
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db')

class Config:
    DATABASE = os.environ.get('CONTACT_LIST_DB', _default_db_path())
```

`_CONFIG_DIR` (`~/.config/contact-list`) is the dir `ensure_private_dir` creates
0700, holding `token.json`, `credentials.json`, `secret_key` (path built at
config.py:40), and `photos/` (`GOOGLE_*` / `PHOTOS_DIR` at config.py:76–81) — but
all of those are created **lazily on first use**, so on a fresh frozen install the
dir may not exist yet when the DB is first opened there. `_load_or_create_secret_key`
creates it only as a side effect of *persisting* a key (config.py:51), and that
path is skipped when a `SECRET_KEY` env var is set (config.py:37); `init_db`
(app.py:35) opens `contacts.db` **before** `create_app`'s
`ensure_private_dir(PHOTOS_DIR)` (app.py:47). Therefore the frozen launcher **must
`ensure_private_dir(_CONFIG_DIR)` before the DB is opened** — `_install_file_logging`
(§3 point 2) does exactly that, since it also writes into this dir before
`create_app`→`init_db`. Putting `contacts.db` there means
**all** mutable state lives in one persistent, private, per-user folder. No new
directory concept is introduced. `PHOTOS_DIR`, `GOOGLE_*`, and the `secret_key`
path are already absolute under `_CONFIG_DIR`, so they need **no** change — they
persist correctly when frozen as-is.

**Cross-platform note.** `~/.config/contact-list` is used verbatim on all three
OSes (Windows creates `C:\Users\<name>\.config\contact-list`, macOS
`~/.config/contact-list`). This intentionally does **not** use each platform's
"native" location (`%APPDATA%`, `~/Library/Application Support`) because doing so
would need a new dependency (`platformdirs`) or hand-rolled per-OS logic for zero
functional gain on a single-user local app, and it keeps the token/DB/photos
co-located exactly as the existing security model (DESIGN.md §6) already assumes.

**Permissions caveat.** The 0700 lock (`ensure_private_dir`, config.py:9-23) is
POSIX-only. macOS honours it; on **Windows** `os.chmod` toggles only the read-only
bit, so 0700 is effectively a no-op there and per-user isolation instead rests on
the Windows user-profile ACLs (each user's home is already private to them). The
`except OSError` in `ensure_private_dir` already tolerates a filesystem that
ignores POSIX modes. The new DESIGN "Packaging & distribution" section (§7) records
this so the cross-OS security stance is explicit, not assumed.

### 2.2 Bundled read-only resources (resource_path helper)

Three read-only resource trees are loaded relative to the source today and must be
(a) packed into the bundle and (b) resolved from `_MEIPASS` at runtime:

- **`templates/`** and **`static/`** — Flask's `Flask(__name__)` (app.py:17)
  resolves these relative to the module's `root_path`, which is wrong inside a
  frozen binary.
- **`migrations/*.sql`** — `db.py:66` reads
  `os.path.dirname(os.path.abspath(__file__))/migrations`.

A single helper gives the correct base directory in both modes:

```python
# new: resources.py
import os
import sys

def resource_path(*parts: str) -> str:
    """Absolute path to a bundled read-only resource.

    Frozen: under the PyInstaller extraction dir (sys._MEIPASS).
    From source: relative to the repo root (this file's directory).
    """
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)
```

- **db.py** changes `migrations_dir` to `resource_path('migrations')`.
- **app.py** changes `Flask(__name__)` to
  `Flask(__name__, template_folder=resource_path('templates'),
  static_folder=resource_path('static'))`. From source, `resource_path` returns
  the same paths Flask would have derived itself, so the non-frozen behaviour is
  byte-identical; frozen, the folders point into `_MEIPASS`.

`resources.py` lives at the repo root next to `resource_path`'s intended base, so
`os.path.dirname(__file__)` is the repo root in source mode. The `templates`,
`static`, and `migrations` trees are added to the bundle via PyInstaller
`--add-data` (§4.1); PyInstaller does **not** auto-collect an app's own template
or data files, so this is mandatory, not optional. No code accesses Flask
`root_path`-relative resources beyond templates/static (no `open_resource` /
`instance_path` usage), so overriding those two folders is sufficient; `migrations`
is the only other `__file__`-relative read and it goes through `resource_path`.

### 2.3 Google OAuth under a frozen binary (routes/sync.py)

`routes/sync.py:51-56` performs Google authorization by spawning a **child Python
process**:

```python
auth_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'google_auth.py')
result = subprocess.run([sys.executable, auth_script], ...)
```

Frozen, this is doubly broken: `sys.executable` is the **app binary**, not a
Python interpreter, and `google_auth.py` is not a runnable file on disk. Running
`[sys.executable, auth_script]` would relaunch the app, not the auth flow — Google
sign-in silently fails.

Fix: make the **frozen binary itself** able to run the auth flow when invoked with
a sentinel flag, and have `authorize()` re-invoke itself with that flag when
frozen. This preserves the existing "auth runs in an isolated child process" design
(the child spins its own `run_local_server` on a temp port and opens a browser for
the OAuth redirect — we do **not** move that into the Flask worker).

**Launcher dispatch (launcher.py, §3)** — before starting the server, check for the
flag and delegate to the unchanged `google_auth.main()`:

```python
# launcher.py (frozen entrypoint)
import sys
if getattr(sys, 'frozen', False) and '--google-auth' in sys.argv:
    from google_auth import main
    sys.exit(main())
```

**authorize() command selection** — pick the child command based on frozen state:

```python
# routes/sync.py — argv choice factored into a plain helper so INV-3 is unit-
# testable WITHOUT a Flask request context (authorize() itself checks
# has_credentials/current_app before it ever reaches subprocess.run, sync.py:44-48).
def _auth_command(frozen: bool) -> list[str]:
    if frozen:
        return [sys.executable, '--google-auth']   # re-invoke this binary
    return [sys.executable, auth_script]           # unchanged: python google_auth.py

# inside authorize():
cmd = _auth_command(getattr(sys, 'frozen', False))
result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
```

`google_auth.py` itself is **unchanged** (its `main()` is imported by the frozen
path and still run as a script from source). `google_auth.py` and `google_sync.py`
must be collected into the bundle as importable modules (they are, being part of
the analysed import graph from `launcher.py`; `google_sync.SCOPES` is imported by
`google_auth`, keeping the single-source-of-truth OAuth scope per the CL-0033
two-way-sync spec). The
Google client libraries need **force-collecting** (§4.1) because they load
submodules dynamically (`googleapiclient.discovery` builds service modules by
name) and ship **package data** (API discovery documents; `phonenumbers` region
metadata) that PyInstaller's import scan does not gather on its own. (Note:
function-level `import` statements *are* detected by PyInstaller's bytecode scan —
the gap is dynamic imports + data files, not the fact that the imports are lazy.)

On Windows (onefile) the `--google-auth` self-re-invoke launches a **second copy**
of the `.exe`, which pays the ~1–2 s onefile unpack again (§4.1) before the OAuth
window appears — expected latency, not a hang.

## 3. The launcher entrypoint (launcher.py)

PyInstaller freezes a single entry script. A new `launcher.py` at the repo root is
that entrypoint; **`app.py` is not modified beyond §2.2's `Flask(...)` line**, and
its `if __name__ == '__main__'` block keeps working for `python app.py` from
source. `launcher.py` responsibilities:

1. **Auth dispatch** (§2.3) — if `--google-auth` in argv, run `google_auth.main()`
   and exit. This must come first, before any server work.
2. **Frozen logging** — when frozen, first `ensure_private_dir(_CONFIG_DIR)` (0700)
   so the config dir exists, then attach a logging file handler writing to
   `~/.config/contact-list/contact-list.log`. Because this runs before anything
   else touches the dir, it also guarantees the dir exists for the subsequent
   frozen `init_db()` that opens `contacts.db` there (§2.1). It then wraps the
   whole server startup (`create_app()` + `app.run`) in a
   `try/except` that calls `logging.exception(...)` on failure. A windowed app
   (§4.3 Windows / §4.4 macOS) has no console and its `sys.stderr` is `None` or
   `os.devnull`, so a bare file handler captures `logging.*` calls but **not** an
   uncaught traceback (e.g. a failed bind) — the explicit `try/except` is what
   makes a startup failure land in the log. This is the only place a frozen
   startup failure is diagnosable. Because `_install_file_logging()` runs **before**
   `create_app()` (so even an `init_db()` failure inside `create_app` is captured),
   it sets the root logger's level and formatter **itself** — it does **not** rely
   on `app.py`'s `logging.basicConfig` (app.py:25-28), which becomes a no-op once
   our handler is attached (`basicConfig` does nothing when the root logger already
   has a handler). The log is opened append-mode with no rotation — acceptable for
   a single-user tool (it grows slowly and can be deleted freely). From source
   (not frozen) `_install_file_logging` is never called, so `basicConfig`
   configures stderr exactly as today.
3. **Single-instance friendliness** — attempt a TCP connect to `127.0.0.1:PORT`.
   If something is already listening (the app is already running), **do not**
   start a second server (it would crash with "address in use"); just open the
   browser to the running instance and exit 0. Any listener on `PORT` is *assumed*
   to be our own instance — a single-user local tool, so a foreign service
   squatting on 5002 is an accepted, unlikely edge (the browser would open to it).
   This is best-effort convenience, **not** a lock: two near-simultaneous launches
   can both observe "not serving", after which the second `app.run` loses the bind
   race and exits with "address in use" (see INV-4).
4. **Start server + open browser** — build the app via `create_app()` and run it.
   A short-lived **daemon** thread polls `127.0.0.1:PORT` until it accepts a
   connection, then calls `webbrowser.open('http://127.0.0.1:PORT')`. The poll is
   **bounded** (gives up after ~15 s) so a startup that never binds does not spin
   the thread forever; if it elapses the browser simply doesn't open and the user
   checks `contact-list.log` (frozen) — a rare degraded case, runtime-only, not
   unit-tested. The main thread runs
   `app.run(host='127.0.0.1', port=PORT, debug=False)` (blocking) — the same bind
   address and port as `app.py:211` (`Config.PORT` is the value behind
   `app.config['PORT']`). Opening the browser from Python replaces `run.sh`'s
   `xdg-open` line and works on all three OSes via the stdlib `webbrowser` module.

The four responsibilities are listed by topic, not execution order: in the sketch
below the single-instance check (3) runs **before** logging setup (2), because the
already-serving path exits immediately and needs no log file.

```python
# launcher.py (sketch)
def main() -> int:
    if getattr(sys, 'frozen', False) and '--google-auth' in sys.argv:
        from google_auth import main as auth_main
        return auth_main()

    from app import create_app
    from config import Config
    port = Config.PORT

    if _port_is_serving('127.0.0.1', port):      # already running
        webbrowser.open(f'http://127.0.0.1:{port}')
        return 0

    if getattr(sys, 'frozen', False):
        _install_file_logging()                  # ~/.config/contact-list/contact-list.log

    # One shared start path. create_app() is INSIDE the try so a frozen
    # init_db()/create_app() failure is logged too — not only app.run bind
    # errors. The try/except is harmless from source (it re-logs to stderr).
    try:
        app = create_app()
        threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
        app.run(host='127.0.0.1', port=port, debug=False)
    except Exception:
        logging.exception('Server startup failed')   # frozen → contact-list.log
        return 1
    return 0
```

The daemon thread is a **narrow, documented** use of a background thread (it does
no application work — it waits for the socket then opens a browser, then the
process is long-lived under `app.run`). This **extends** the CL-0046 carve-out
already recorded in DESIGN.md §7.2 (a different purpose — that thread defers a
restart flush, this one opens the browser once); §7 lists the note added there.

## 4. Packaging per OS

All three builds share **one PyInstaller invocation shape** (same entry script,
same `--add-data`, same hidden-import collection); they differ only in the OS
wrapper produced afterwards. The shared parts live in a **PyInstaller spec file**
(`packaging/contact-list.spec`) checked into the repo so local and CI builds are
byte-for-byte the same recipe (this is the "catch errors locally first" guarantee).

### 4.1 Shared PyInstaller configuration (packaging/contact-list.spec)

- **Entry:** `launcher.py`.
- **Bundled data** (`--add-data` / `datas=`): `templates/`, `static/`,
  `migrations/` (the three trees §2.2 resolves via `resource_path`).
- **Force-collected packages** (`--collect-all` / `collect_all()` is required or
  they are missing at runtime — because they load submodules dynamically and/or
  ship package data PyInstaller's import scan does not gather on its own):
  `googleapiclient` (dynamic discovery-based service modules + bundled discovery
  docs), `google_auth_oauthlib`, `google.auth`, `google_auth_httplib2`,
  `phonenumbers` (ships region metadata as package data), `PIL`. The exact
  hidden-import list is finalised empirically during implementation by running the
  frozen app through: launch → open a contact with a photo → attempt a Google sync
  → attempt authorize; any `ModuleNotFoundError`/missing-data error names the next
  package to collect.
- **Mode:** **onedir** on Linux and macOS (the AppImage / `.app` wrapper is
  already a single distributable, and onedir carries no per-launch self-extraction
  cost — the `.app` runs in place and a FUSE-mounted AppImage runs without
  unpacking; only a FUSE-less host falls back to extract-and-run). **onefile** on
  Windows (the only way to ship a literal single `.exe`; it self-extracts to a
  temp dir on **every** launch, ~1–2 s).
- **Cold-start budget.** DESIGN.md §7.1's `< 500 ms` cold-start target is
  **treated as** a source-mode figure (measured for `python app.py`); §7 adds that
  qualifier to §7.1 itself. The frozen launchers'
  first-paint is dominated by bundle unpack/extract and is **explicitly exempted**
  from that target — in particular the Windows onefile every-launch unpack
  (~1–2 s) is an accepted trade-off for single-file delivery. §7 records this
  exemption in DESIGN.md §7.1.
- **Icon:** generated from `packaging/icon.png` (the processed, transparent-corner
  master added in this change; on disk at `packaging/icon.png`) into the per-OS
  formats below.

### 4.2 Linux → AppImage (packaging/build-linux.sh)

1. `pyinstaller packaging/contact-list.spec` → `dist/Contact-List/` (onedir).
2. Assemble an AppDir: the onedir tree under `usr/`, an `AppRun` that execs the
   binary, a top-level `contact-list.desktop` (mirrors the installed one, §5.3),
   and `contact-list.png` (256px, from `packaging/icon.png`).
3. `appimagetool AppDir Contact-List-x86_64.AppImage`.

`appimagetool` is fetched into `packaging/.tools/` (gitignored) on first run,
**pinned to a specific release URL and verified against a recorded SHA-256** (a
moved or altered download fails the build loudly instead of silently); building
uses `--appimage-extract-and-run` so no system FUSE is required on the build host.
This script is the **local pre-flight** and the exact steps CI runs.

### 4.3 Windows → .exe (packaging/build-windows.sh, run under Wine locally)

- **Local (Wine) pre-flight:** a one-time `packaging/wine-setup.sh` installs a
  Windows Python 3.12 into the Wine prefix and `pip install -r requirements.txt
  pyinstaller`. `build-windows.sh` then runs `wine pyinstaller
  packaging/contact-list.spec` with `--onefile --windowed --icon
  packaging/icon.ico` → `dist/Contact-List.exe`. Because Wine is a Windows
  reimplementation, this is a **pre-flight to catch packaging errors**, not the
  shipped artefact.
- **`--windowed` (no console):** the browser is the UI, so no black console window
  is shown. The trade-off — a silent failure if the server can't start — is
  covered by the frozen file-log (§3, point 2); the `try/except` around startup
  writes the traceback to `contact-list.log`.
- **Official build:** the native `windows-latest` CI runner (§6) runs the identical
  spec, producing the `.exe` that is actually published.

### 4.4 macOS → .dmg (CI-only, packaging/build-macos.sh)

macOS **cannot** be built or legally virtualised on Linux (Apple's licence permits
macOS only on Apple hardware; no legitimate container image exists). It is built
exclusively on the `macos-latest` CI runner (a real Mac), so there is **no** local
pre-flight for macOS — the mitigation is the CI dry-run mode (§6) that builds all
three as throwaway artefacts before a real tag is cut.

1. `pyinstaller ... --windowed --icon packaging/icon.icns` → `dist/Contact List.app`
   (onedir bundle).
2. **Ad-hoc code-sign** the assembled `.app` (`codesign --force --sign - "Contact
   List.app"`). Apple Silicon (arm64) refuses to execute **unsigned** Mach-O code,
   so *a* signature is mandatory — ad-hoc suffices. PyInstaller already ad-hoc-signs
   the raw binary during the build; this step **re-signs** after the `.app` is
   assembled and the icon staged, so the bundle's signature stays valid. It is
   **not** notarization (which needs a paid Apple Developer ID; out of scope, §8).
3. Stage a DMG source folder containing the `.app` **and** an
   `ln -s /Applications` symlink, then `hdiutil create -volname "Contact List"
   -srcfolder <staged-dir> -format UDZO Contact-List.dmg` — the symlink is staged
   into the folder *before* `hdiutil` runs, so the mounted image shows an
   Applications shortcut to drag the app onto.

**First-launch friction (unsigned):** without notarization, Gatekeeper warns on
first open; the user right-clicks → Open once. This is documented in the README
download section (§5.4), not engineered away.

**Architecture scope:** `macos-latest` is Apple Silicon, so v1 ships an **arm64**
`.dmg`, which runs on every Apple-Silicon Mac (2020+). Intel Macs are **not**
covered by v1 (a universal2 build needs a universal Python and extra CI wiring);
this is an explicit, stated limitation, revisited only on demand (§8).

### 4.5 Icon derivation (packaging/make-icons.sh)

All OS icon formats derive from the single master `packaging/icon.png` (1254²,
transparent corners, produced in this change from `packaging/icon-source.png` and
committed as part of implementing this spec):

- **`icon.ico`** (Windows) — multi-size (16/32/48/64/128/256) via Pillow
  (`Image.save('icon.ico', sizes=[...])`), which is already a dependency.
- **`icon.icns`** (macOS) — built on the macOS runner via `iconutil` from an
  `.iconset` of PNGs (also Pillow-resized); `iconutil` is macOS-only, hence this
  step runs in the macOS job.
- **`contact-list.png`** (Linux/AppImage, 256px) — Pillow resize.

These per-OS formats are build artefacts (gitignored); the PNG masters
(`icon-source.png`, `icon.png`) plus the in-app `static/icon.png` favicon are the
committed assets (§5.2).

## 5. In-app icon / favicon and desktop integration

### 5.1 App favicon refresh (pending — build wiring)

The browser-tab favicon currently uses the old flat-blue `static/icon.svg`
(`templates/base.html:7`, `<link rel="icon" ... filename='icon.svg'>`). This spec
**will** replace it, for visual consistency with the launcher: `make-icons.sh`
generates `static/icon.png` (e.g. 64px) from `packaging/icon.png` **once, and that
PNG is then committed** (unlike the per-OS `.ico`/`.icns`, which stay gitignored)
so source runs have a favicon with no build step; `base.html:7`'s
`<link>` is repointed (`href` → `icon.png` **and** `type="image/svg+xml"` →
`type="image/png"` — both attributes change, not just the href), and the stale
`static/icon.svg` is retired. **None of
this is done yet** — it is implementation work tracked in §9's file table.
*(Only the **desktop-menu** icon on the dev machine was updated in this session —
installed into `~/.local/share/icons/hicolor/*/apps/contact-list.png`, old
scalable SVG retired. That is a local-machine change, separate from and
independent of the still-pending repo template edit specified here.)*

### 5.2 Committed vs generated assets

Committed as part of implementing this spec, in two groups:
- **Three `packaging/` masters that already exist on disk (currently untracked):**
  `packaging/icon-source.png` (raw generator output), `packaging/icon.png`
  (processed transparent master), `packaging/old-icon-flatblue.svg` (retired
  original, kept for provenance).
- **`static/icon.png` — the in-app favicon — does not exist yet**; it is generated
  from `packaging/icon.png` during implementation and committed so source runs have
  a favicon without a build step.

Generated at build time and gitignored: the per-OS `icon.ico`, `icon.icns`, and
`contact-list.png`.

### 5.3 AppImage desktop metadata

The AppImage's internal `contact-list.desktop` mirrors the app's identity
(`Name=Contact List`, `Icon=contact-list`, `Categories=Office;`) so file managers
that integrate AppImages show the right name/icon. This is packaging metadata
inside the AppImage, independent of the user's system `contact-list.desktop`.

### 5.4 README download/run instructions

A new README section documents, per OS: where to download (the GitHub Release
page), the one-time unblock step (macOS right-click→Open; Windows SmartScreen
"More info → Run anyway"), and that Google sync additionally requires the user to
drop their own `credentials.json` into `~/.config/contact-list/` (unchanged from
today — the launcher does not ship Google client secrets).

## 6. Build & release automation (.github/workflows/release.yml)

A **new** workflow, separate from the existing `ci.yml` (which is untouched and
keeps running lint/type/test on every push). Triggers:

- **`push` on tags `v*`** → real release: build all three, create a GitHub Release
  for the tag, attach the three files.
- **`workflow_dispatch` with `dry_run: true`** → rehearsal: build all three,
  upload as **workflow artifacts** only; create **no** Release. This is the macOS
  blind-spot mitigation — exercise the Mac build (and all three) before tagging.

Structure — three build jobs (each OS needs a different wrapper, so per-OS jobs are
clearer than a matrix with heavy `if runner.os` branching) plus one release job:

| Job | Runner | Produces |
|-----|--------|----------|
| `build-linux` | `ubuntu-latest` | `Contact-List-x86_64.AppImage` |
| `build-windows` | `windows-latest` | `Contact-List.exe` |
| `build-macos` | `macos-latest` | `Contact-List.dmg` |
| `release` | `ubuntu-latest` | GitHub Release with all three attached (skipped on dry-run) |

- Python **3.12** (the app's floor) via `actions/setup-python@v6`;
  `actions/checkout@v7` — matching the versions already pinned in `ci.yml`. The
  `upload-artifact` / `download-artifact` / `action-gh-release` majors are pinned
  to whatever is current at implementation time — the workflow file carries the
  concrete pins; this spec avoids naming a major that may go stale (global rule 5a:
  CI action versions stay current).
- Each build job: checkout → setup-python → `pip install -r requirements.txt
  pyinstaller` → `make-icons.sh` → run its `build-*.sh` →
  `actions/upload-artifact` (current major).
- `release` job: `needs: [build-linux, build-windows, build-macos]`,
  `actions/download-artifact` (current major), then `softprops/action-gh-release` (current major)
  attaching the three files; guarded by `if: startsWith(github.ref, 'refs/tags/')`
  so `dry_run` stops after the artifacts.
- The Release version/filenames derive from the tag (`${{ github.ref_name }}`).
- Public repo → free Linux/Windows/macOS minutes; no cost gate (global rule 6
  push cadence still applies to *pushing the tag*, which is the user's call).

## 7. DESIGN.md updates

- **§3 Dependency budget** — a one-line note that PyInstaller, appimagetool, and
  the platform icon tools are **build-time only**, not runtime deps, so the <8
  runtime-package budget is unaffected. (Mirrors the existing Pillow-exception
  prose style.)
- **§7.1 cold-start** — a one-line note that the `< 500 ms` target is a
  source-mode figure; the frozen launchers' first-launch unpack (notably the
  Windows onefile every-launch extraction, ~1–2 s) is explicitly exempt (§4.1).
- **§7.2 background-threads carve-out** — extend the existing CL-0046 carve-out to
  also cover the launcher's one-shot browser-open daemon thread (does no
  application work; opens the browser once after the socket is up).
- **New §"Packaging & distribution"** — record the frozen-vs-source resource model
  (§2), the `~/.config/contact-list` state location when frozen, the per-OS
  formats, the unsigned/ad-hoc-signed distribution posture (macOS Gatekeeper,
  Windows SmartScreen), and the note that the config-dir 0700 lock is POSIX-only —
  Windows per-user isolation rests on user-profile ACLs (§2.1) — so the cross-OS
  security stance is documented, not implicit.
- **§9 route table** — no change: no new routes are added (`authorize` is the same
  route, only its child command differs).

## 8. Out of scope

- **No code signing / notarization.** macOS ships ad-hoc-signed (runs, but warns);
  Windows ships unsigned (SmartScreen warns). Both need paid developer accounts.
- **No Intel-mac / universal2 build** in v1 — Apple Silicon `.dmg` only (§4.4).
- **No auto-update** mechanism — the user re-downloads from the Release page.
- **No Linux packaging beyond AppImage** (no `.deb`/`.rpm`/Flatpak in v1).
- **No change to `run.sh`** — the from-source path is untouched; the launcher's
  browser-open replaces `xdg-open` only inside the frozen binary.
- **No bundling of Google client secrets** — the user still supplies their own
  `credentials.json` for sync (this spec §5.4 / the README download section it
  specifies).
- **Tagging / publishing the release** is a **separate follow-on step** after the
  launchers are verified, not part of this spec. A `[1.0.0]` CHANGELOG section
  already exists (untagged), so the follow-on is creating the git tag + GitHub
  Release — and deciding whether the current `[Unreleased]` items publish as
  `1.0.0`'s actual first release or as a `1.1.0` — not writing the changelog
  section.

## 9. New / changed files

| File | Change | ~lines |
|------|--------|--------|
| `launcher.py` | **new** — frozen entrypoint: auth dispatch, single-instance check, server + browser-open, frozen file-logging | ~70 |
| `resources.py` | **new** — `resource_path()` helper (§2.2) | ~12 |
| `config.py` | frozen-aware `DATABASE` default (§2.1) | ~8 |
| `db.py` | `migrations_dir` via `resource_path('migrations')` (§2.2) | ~2 |
| `app.py` | `Flask(...)` with `resource_path` template/static folders (§2.2) | ~3 |
| `routes/sync.py` | frozen-aware auth child command (§2.3) | ~6 |
| `packaging/contact-list.spec` | **new** — shared PyInstaller recipe (§4.1) | ~50 |
| `packaging/build-linux.sh` | **new** — AppImage build + local pre-flight (§4.2) | ~40 |
| `packaging/build-windows.sh` + `wine-setup.sh` | **new** — Wine pre-flight + `.exe` (§4.3) | ~50 |
| `packaging/build-macos.sh` | **new** — `.app` + ad-hoc sign + `.dmg` (§4.4) | ~35 |
| `packaging/make-icons.sh` | **new** — `.ico`/`.icns`/PNG from `icon.png` (§4.5) | ~25 |
| `.github/workflows/release.yml` | **new** — 3 build jobs + release job (§6) | ~90 |
| `templates/base.html` (favicon `<link>`) | repoint `href` → `icon.png` and `type` → `image/png` (§5.1) | ~1 |
| `static/icon.png` | **new** — committed favicon from master | asset |
| `static/icon.svg` | **retire** — replaced by PNG favicon | — |
| `packaging/icon-source.png`, `icon.png`, `old-icon-flatblue.svg` | **new** — committed masters (§5.2) | asset |
| `.gitignore` | add `packaging/.tools/` + generated `packaging/*.ico`/`*.icns`/`contact-list.png` (`dist/`, `build/` already ignored) | ~2 |
| `README.md` | **new download/run section** — per-OS download, unblock steps, `credentials.json` note (§5.4) | ~20 |
| `DESIGN.md` | §3 note, §7.1 cold-start note, §7.2 carve-out, new Packaging section (§7) | ~15 |
| `tests/test_packaging.py` | **new** — unit tests §10 | ~40 |

## 10. Testing & verification

**Unit tests** (run in the normal suite; all assert the *source-mode* behaviour and
the frozen branch selection without actually freezing):

- `resource_path('migrations')` returns the repo `migrations/` dir from source, and
  respects `sys._MEIPASS` when it is set (monkeypatch `sys._MEIPASS` → asserted
  base changes).
- `config._default_db_path()` returns the next-to-source path when
  `sys.frozen` is unset, and the `~/.config/contact-list/contacts.db` path when
  `sys.frozen` is monkeypatched truthy.
- Auth child-command selection (INV-3): unit-test the plain helper
  `routes/sync._auth_command` directly — `_auth_command(True)` →
  `[sys.executable, '--google-auth']`, `_auth_command(False)` →
  `[sys.executable, <google_auth.py>]`. Testing the helper (not `authorize()`)
  keeps the test out of Flask's request context and away from the
  `has_credentials`/`current_app` preconditions `authorize()` checks first
  (sync.py:44-48); no real OAuth flow runs.
- `launcher.main` single-instance branch (INV-4): monkeypatch `_port_is_serving`
  → `True`, `webbrowser.open` → recorder, and `app.create_app` → a sentinel that
  fails the test if called; assert `main()` opens the browser to
  `http://127.0.0.1:PORT` and returns 0 **without** building or running the app.
- `launcher.main` server path binds loopback (INV-6): monkeypatch `_port_is_serving`
  → `False`, `create_app` → a throwaway `Flask(__name__)` (so the test runs **no**
  `init_db` and touches **no** real DB or config dir), and that app's `run` →
  a recorder (so it returns instead of blocking); assert `run` is called once with
  `host='127.0.0.1'`. Any launcher test that lets the real `create_app` run must
  first point `CONTACT_LIST_DB` at a temp file and isolate the config dir, exactly
  as the existing suite does via `test_config` (app.py:19-22) — the launcher path
  passes no `test_config`, so tests must inject isolation themselves. Note that
  merely *importing* `config` runs `Config.SECRET_KEY = _load_or_create_secret_key()`
  (config.py), which writes a `secret_key` into the real `~/.config/contact-list`
  unless `SECRET_KEY` is set in the test env — so the new `config`/`launcher` tests
  should set `SECRET_KEY` (or redirect `HOME`/the config dir to a tmp path).
- Existing suite stays green — the frozen branches are inert when not frozen, so no
  current test changes behaviour. (INV-5 is structural — verified by grepping
  `requirements.txt` for `pyinstaller` (absent), not unit-tested. INV-7's frozen
  file-log and INV-4's browser-poll bound are runtime-only, exercised by the
  local-launch checklist below, not the unit suite.)

**Local build verification** (the "catch errors before CI" loop):

- **Linux:** run `packaging/build-linux.sh`; launch the resulting `.AppImage` from
  a **clean** environment (e.g. a temp dir with the repo `venv`/source *not* on
  `PYTHONPATH`) → app opens in the browser; **add a contact, quit, relaunch → the
  contact persists** (proves §2.1's persistent data dir); open a contact with a
  photo (proves `static`/`PHOTOS_DIR` + Pillow are bundled); trigger a Google sync
  and `authorize` → the flow launches (with `credentials.json` present) or fails
  *cleanly* with the "credentials not found" message (proves §2.3 dispatch, not a
  crash).
- **Windows (Wine):** run `wine-setup.sh` then `build-windows.sh`; run
  `wine dist/Contact-List.exe`; `curl http://127.0.0.1:5002` returns the contact
  list HTML (server + data dir work under the frozen `.exe`).

**CI verification:** run the workflow via `workflow_dispatch` `dry_run: true` first
→ all three artefacts build and download; verify the macOS `.dmg` on a real Mac (or
at minimum that the job is green) **before** pushing a real `v*` tag.

## 11. Invariants

- **INV-1** When frozen, **all** mutable state (database, `photos/`, `token.json`,
  `secret_key`, `contact-list.log`) lives under `~/.config/contact-list` — never
  inside the ephemeral `_MEIPASS` extraction dir — so nothing is lost between runs.
  From source, the database path is unchanged (next to the code). *(Testable:
  `_default_db_path()` under monkeypatched `sys.frozen`.)*
- **INV-2** Bundled read-only resources (`templates`, `static`, `migrations`) are
  resolved via `resource_path` → `_MEIPASS` when frozen, repo root from source, and
  are all present in the bundle (`--add-data`). *(Testable: `resource_path` base
  switches with `sys._MEIPASS`; run-time proof is the local launch test §10.)*
- **INV-3** Google OAuth works when frozen: `authorize()` re-invokes the app binary
  with `--google-auth`, which `launcher.py` routes to the unchanged
  `google_auth.main()`; from source it still runs `[python, google_auth.py]`.
  Nothing user-supplied enters the child argv (the flag is a constant; the child
  reads only files under `~/.config/contact-list`). *(Testable: argv selection
  under monkeypatched `sys.frozen`.)*
- **INV-4** When the launcher detects the app already serving on `127.0.0.1:PORT`
  it does **not** start a second server: it opens the browser to the existing
  instance and exits 0. This is best-effort, not a hard mutual-exclusion — any
  listener on `PORT` is treated as our instance (foreign-service edge accepted,
  §3), and two near-simultaneous launches can still race so the loser exits with
  "address in use". In the normal server-startup path the browser is opened only
  **after** the socket accepts a connection. *(Testable: monkeypatched
  `_port_is_serving` → `main()` opens the browser and returns 0 without running
  the app; §10.)*
- **INV-5** No new **runtime** dependency is added: PyInstaller, appimagetool, and
  the icon tools are build-time only and never enter `requirements.txt`, so the
  DESIGN.md §3 runtime budget (<8 packages) is intact. *(Structural — verified by
  `pyinstaller` being absent from `requirements.txt`; not unit-tested.)*
- **INV-6** The bundled app binds `127.0.0.1` only (the launcher's `app.run`
  passes `host='127.0.0.1'`, matching `app.py:211`); packaging adds no network
  exposure. *(Testable: monkeypatch `flask.Flask.run` with a recorder and assert
  the launcher calls it with `host='127.0.0.1'` — the existing suite exercises
  `create_app` but never `app.run`, so the launcher's bind needs its own
  assertion.)*
- **INV-7** A frozen windowed app (no console) writes startup errors and tracebacks
  to `~/.config/contact-list/contact-list.log` — via both a logging file handler
  **and** the `try/except` wrap around `create_app()`/`app.run` (§3, point 2),
  which is what captures an otherwise-uncaught bind failure — so a silent failure
  is diagnosable. From source, logging is unchanged (stderr). *(Runtime-only; not
  unit-tested — exercised by the §10 local-launch checklist.)*
