# System-tray icon with Open / Restart / Quit (CL-0052)

**Status:** DRAFT — design approved by the user (2026-07-12). The Linux backend
selection (§4) and the AppImage bundling recipe (§6) are being finalised from an
in-flight deep-research pass (run `wf_0fe49d44-bb6`) into the Linux tray landscape;
those two sections are marked _[pending research]_ and will be replaced with the
grounded, cited conclusions before the spec goes through `/cold-eyes`. Not yet
implemented. Per global rule 14 this spec runs through `/cold-eyes` to
convergence before any code is written.

## 1. Problem & overview

The one-file downloads (`.AppImage` / `.exe` / `.dmg`, CL-0049) are launched from
a desktop icon with **no terminal attached**. Today, once launched, the app runs
a local web server on `127.0.0.1:5002`, opens the browser, and then has **no
visible presence** — there is no indication it is running, and the only ways to
control it are the Settings-page Restart/Shutdown buttons (CL-0046), which require
already having the page open.

This change adds a **system-tray / menu-bar icon** with a right-click menu:

- **Open Contact List** — open the browser to `http://127.0.0.1:5002` (also the
  left-click default action where the OS supports one).
- **Restart** — relaunch the app with fresh code/state (reuses the CL-0046
  restart mechanism).
- **Quit** — stop the web server and remove the icon, exiting the process.

The icon gives the app a persistent, discoverable control point independent of
the browser tab.

## 2. Scope & decisions (user-approved 2026-07-12)

1. **Cross-platform**, targeting Windows, macOS, and Linux from one codebase.
2. **Graceful fallback:** if a tray cannot be created (unsupported desktop,
   headless box), the app logs one line and behaves exactly as today — server
   runs, browser opens, no icon. Nobody is ever worse off. (§7)
3. **Everywhere, not just frozen:** the tray also appears when running from source
   via `./run.sh`. `run.sh` is repointed to `launcher.py` (§5). Running
   `python app.py` directly stays a **headless server** (what the tests and CI
   use) so this change cannot destabilise the suite.
4. **Menu = Open / Restart / Quit**, exactly (YAGNI — no status submenu, no
   settings shortcuts in v1).
5. **New dependency `pystray` approved**, raising the DESIGN.md §3 direct-runtime
   budget from "under 8" to **8**, documented with justification like the Pillow
   exception (§8).

## 3. Library choice

**`pystray`** (latest 0.19.5) — the standard cross-platform Python tray library.

- Reuses **Pillow** (already a dependency, CL-0035) for the icon image.
- Small helpers, loaded only on the OS that needs them: `python-xlib` (Linux
  Xorg backend), a PyObjC framework (macOS), nothing extra on Windows. `six` is a
  transitive dep.

Rejected alternatives: **Qt `QSystemTrayIcon`** (pulls ~50 MB of framework into a
tiny app — violates the "no JS/GUI framework overhead" ethos, DESIGN.md §3);
**three OS-specific libraries** (`infi.systray` + `rumps` + a hand-rolled Linux
AppIndicator — three deps, three code paths, far more surface than warranted).

## 4. Linux backend selection — _[pending research]_

pystray exposes three Linux backends: `appindicator` (GObject/`gi` +
AyatanaAppIndicator, speaks StatusNotifierItem over DBus), `gtk` (deprecated
GtkStatusIcon), and `xorg` (pure `python-xlib`, draws its own window). Which one
integrates with the modern SNI tray used by KDE Plasma (the target user's
desktop), which work on GNOME/XFCE/Cinnamon/MATE, and how to force the choice
(`PYSTRAY_BACKEND`) — **to be filled in from the deep-research pass** (run
`wf_0fe49d44-bb6`). The known tension: the `appindicator` backend gives a proper
KDE menu but needs the PyGObject/AppIndicator system stack (hard to bundle); the
`xorg` backend needs no GObject but may not integrate with KDE's SNI tray. The
research resolves this trade-off with cited evidence before we commit.

## 5. Reshaped startup (`launcher.py`)

Today `launcher.main()` runs the Werkzeug dev server on the **main thread**
(`app.run(...)`), with a daemon thread that opens the browser once the socket is
up. A tray icon **must own the main thread** (an OS requirement, strict on macOS
AppKit), so:

- Build a **stoppable server handle** with
  `werkzeug.serving.make_server('127.0.0.1', port, app)` and run
  `server.serve_forever()` on a **dedicated background thread**. The handle is
  what lets Quit call `server.shutdown()` cleanly (a plain `app.run()` gives no
  such handle).
- Open the browser when the socket is ready (existing `_open_when_ready` logic,
  unchanged).
- Run the tray icon loop on the **main thread**.
- **`run.sh`** is changed from `exec … python app.py` to `exec … python
  launcher.py` so the from-source path gets the same tray + startup logic.
- The **already-running second-launch** check (`_port_is_serving` → open browser
  → exit) is unchanged: the tray belongs to the first instance only; a second
  launch never creates a second icon.

### Menu action semantics

- **Open** → `webbrowser.open('http://127.0.0.1:{port}')`.
- **Restart** → reuse the CL-0046 mechanism in `server_control.py` (spawn a fresh
  detached process via `subprocess.Popen(close_fds=True, start_new_session=True)`,
  then `os._exit(0)`). The respawn target must be the **tray-capable entrypoint**
  (`launcher.py` / the frozen exe) so the new process brings up a new icon. If the
  existing `server_control` respawn hard-codes assumptions that break this, factor
  a shared `respawn()` helper both the Settings route and the tray call (rule 3
  reuse), rather than duplicating it.
- **Quit** → `server.shutdown()` (unblocks `serve_forever`), `icon.stop()`, then
  return 0. Exits cleanly with no orphaned server thread.

## 6. Packaging / AppImage bundling — _[pending research]_

The PyInstaller spec (`packaging/contact-list.spec`) must bundle the chosen
pystray backend so the tray works on a machine **without** PyGObject/AppIndicator
pre-installed (the whole point of a self-contained AppImage). Concretely this
means either `collect_all('gi')` + the GObject-Introspection `.typelib` files +
the AyatanaAppIndicator shared libraries, **or** — if the research recommends the
`xorg` backend — only `python-xlib`, with no GObject at all. Exact
`hiddenimports` / `datas` / `binaries` additions, PyInstaller hooks, and known
gotchas — **to be filled in from the deep-research pass**. Also: add the tray
icon PNG (`packaging/contact-list.png`) to the spec's `datas` so it is resolvable
at runtime via `resources.resource_path(...)`; from source, load it directly.

## 7. Error handling & graceful fallback

- **Tray unavailable** (import error, no display, backend init failure): catch,
  log one `INFO`/`WARNING` line ("system tray unavailable; running without an
  icon"), and fall back to **joining the server thread** — i.e. behave exactly as
  today. The app is fully functional without the icon.
- **Robust availability detection** — how to decide "no tray is really present"
  before committing to the icon loop (vs. an Xorg backend that blocks forever on a
  tray that never appears) is one of the research questions (§4/research item 7);
  the concrete guard goes here once known.
- **Restart spawn failure** → keep the current server serving (the CL-0046 helper
  already degrades this way).

## 8. Dependency & documentation changes

- `requirements.txt`: add `pystray>=0.19,<0.20` (major-capped per the deps-latest
  policy; 0.19.5 is current).
- **DESIGN.md §3:** raise the direct-runtime budget from "under 8" to **8**; add
  `pystray` to the runtime list with the justification (tray icon = core desktop
  UX), mirroring the Pillow exception wording; note its platform backends
  (`python-xlib` / PyObjC / AppIndicator system libs) as transitive / build-time.
  Add a §7.2 carve-out documenting the tray-owns-main-thread + server-on-one-
  background-thread model (analogous to the CL-0046 one-shot-thread carve-out):
  the background thread runs the server event loop only; no shared mutable app
  state crosses threads beyond the server socket.
- **CHANGELOG.md** `[Unreleased]`: an Added entry.

## 9. Testing

- **Unit-test the three menu actions** with the server and `webbrowser` faked:
  Open calls `webbrowser.open` with the right URL; Quit calls `server.shutdown()`
  + `icon.stop()`; Restart calls the respawn helper (patched, never actually
  spawning — mirror the `PYTEST_CURRENT_TEST` guard in `server_control`).
- **Fallback path:** simulate pystray import/init failure and assert the launcher
  still serves headlessly without raising.
- **Packaging test:** assert `pystray` is present in `requirements.txt` (mirrors
  the existing dependency assertions in `tests/test_packaging.py`).
- The icon **actually rendering** cannot be unit-tested (needs a live desktop),
  same as `webbrowser.open` is not tested. Covered instead by the manual spike
  below.

## 10. Implementation order (de-risk Linux first)

1. **Spike (throwaway):** finalise §4/§6 from research, then build the AppImage
   and confirm the icon appears in the target KDE tray with a working menu,
   **before** building anything else. This is the one platform-risk gate.
2. `tray.py` module + unit tests.
3. `launcher.py` restructure (stoppable server handle, tray on main thread,
   fallback) + `run.sh` repoint.
4. PyInstaller spec + `requirements.txt` + DESIGN.md / CHANGELOG updates.
5. Verify on all three OSes via the release build.

## Open invariants (to harden during cold-eyes)

- **INV-1:** exactly one server instance per process; Quit releases the port
  (no orphaned thread).
- **INV-2:** a second launch never creates a second icon.
- **INV-3:** tray failure ⇒ headless server still runs (never a dead app).
- **INV-4:** `python app.py` remains headless (no tray) so tests/CI are unaffected.
