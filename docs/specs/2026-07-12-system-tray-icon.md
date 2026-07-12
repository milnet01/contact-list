# System-tray icon with Open / Restart / Quit (CL-0052)

**Status:** DRAFT — design approved by the user (2026-07-12). The Linux backend
selection (§4) and the AppImage bundling recipe (§6) are now finalised from a
completed deep-research pass (run `wf_0fe49d44-bb6`, 24 confirmed claims / 21
sources; key sources cited inline and listed in §11). Not yet implemented. Per
global rule 14 this spec runs through `/cold-eyes` to convergence before any code
is written.

## Contents

1. Problem & overview · 2. Scope & decisions · 3. Library choice ·
4. Linux backend selection (`appindicator`) · 5. Reshaped startup (`launcher.py`) ·
6. Packaging / AppImage bundling · 7. Error handling & graceful fallback ·
8. Dependency & documentation changes · 9. Testing · 10. Implementation order ·
Open invariants (INV-1…5) · 11. Sources

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
   `python app.py` directly stays a **headless server** (the plain app entrypoint
   the test suite imports via `create_app()`; the tray lives only in `launcher.py`)
   so this change cannot destabilise the suite.
4. **Menu = Open / Restart / Quit**, exactly (YAGNI — no status submenu, no
   settings shortcuts in v1).
5. **New dependency `pystray` approved**, raising the DESIGN.md §3 direct-runtime
   budget from "under 8" to **8**, documented with justification like the Pillow
   exception (§8).

## 3. Library choice

**`pystray`** (latest 0.19.5) — the standard cross-platform Python tray library.

- Reuses **Pillow** (already a dependency, CL-0035) for the icon image.
- Platform helpers pulled in per-OS: a PyObjC framework (macOS), nothing extra on
  Windows. On Linux we drive the `appindicator` backend (§4.2), so `python-xlib`
  is installed as a transitive dep but stays **dormant** (the `xorg` backend is
  never selected). `six` is a transitive dep.

Rejected alternatives: **Qt `QSystemTrayIcon`** (pulls ~50 MB of framework into a
tiny app — violates the "no JS/GUI framework overhead" ethos, DESIGN.md §3);
**three OS-specific libraries** (`infi.systray` + `rumps` + a hand-rolled Linux
AppIndicator — three deps, three code paths, far more surface than warranted).

## 4. Linux backend selection — **`appindicator`** (SNI over DBus)

### 4.1 The mechanism: SNI, not XEmbed

The modern Linux tray is **StatusNotifierItem (SNI)** — a **D-Bus** protocol, not
the legacy X11/XEmbed "system tray" embedding. Each app registers a
`StatusNotifierItem`; a `StatusNotifierWatcher` (well-known name
`org.kde.StatusNotifierWatcher`) tracks items; the panel registers as a
`StatusNotifierHost` to render them [freedesktop SNI spec; KDE
StatusNotifierWatcher XML]. Because it is DBus-based and transport-agnostic, SNI
works identically under **Wayland and X11** — which matters because KDE Plasma
increasingly defaults to a Wayland session.

### 4.2 pystray's three backends, and why only one fits

pystray picks a Linux backend in the order `appindicator` → `gtk` → `xorg`, and
the choice can be forced with the `PYSTRAY_BACKEND` environment variable [pystray
usage docs]. Their capabilities decide this for us:

| Backend | Menu support | Tray mechanism | Wayland | Verdict |
|---|---|---|---|---|
| `xorg` (pure `python-xlib`) | **None except a default click action** | legacy X11 | **X11 only** | ❌ can't show Open/Restart/Quit |
| `gtk` (GtkStatusIcon) | full | deprecated XEmbed; needs a shell extension even on GNOME | breaks | ❌ legacy, fragile |
| `appindicator` (Ayatana/`gi`) | all features except a menu *default* action | **SNI over DBus (dbusmenu)** | ✅ | ✅ **chosen** |

The **`xorg` backend is disqualified**: pystray's own docs state it "supports no
menu functionality except a default action" [pystray usage docs] — our entire
feature is a three-item right-click menu, so xorg physically cannot deliver it.
The `gtk` backend uses the deprecated GtkStatusIcon (legacy XEmbed) and "may not
be fully functional without installing desktop environment extensions." That
leaves **`appindicator`**, which speaks SNI over DBus, integrates with KDE
Plasma's native SNI host via KSNI, and is pystray's own preferred backend
[pystray FAQ; libayatana-appindicator README]. It supports every feature we need
(we do not use a menu default action).

**Decision:** default `PYSTRAY_BACKEND` to `appindicator` before importing pystray
(via `setdefault`, §5), so pystray's auto-selection can never *silently* fall
through to the menuless `xorg` backend — the only way to reach `xorg` is an
explicit user `PYSTRAY_BACKEND=xorg`, their own informed choice. If the
appindicator backend fails to load, we fall back to **headless** (§7) — never to a
degraded icon. This preserves INV-5 (an icon we bring up ourselves always carries
the full menu).

### 4.3 Per-desktop reality

- **KDE Plasma (target):** native SNI host — works out of the box, no extension.
- **XFCE, MATE, Cinnamon, Budgie, LXDE:** render AppIndicator/SNI items via
  libayatana-appindicator — work out of the box.
- **GNOME Shell:** has **no** native tray; the user needs the "AppIndicator and
  KStatusNotifierItem Support" extension (≈3 M downloads, supports GNOME 45–50).
  This is a host-side prerequisite we cannot bundle; on stock GNOME the app
  degrades gracefully to headless (§7). Documented as a known limitation.

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
- Run the tray icon loop on the **main thread** (in `tray.py`, see §10). On Linux,
  set `os.environ.setdefault('PYSTRAY_BACKEND', 'appindicator')` **before**
  importing pystray (§4.2). `setdefault` pins pystray's *auto*-selection to
  appindicator so it can never silently fall through to the menuless `xorg`
  backend, while still honouring a deliberate `PYSTRAY_BACKEND=…` the user
  exported themselves — matching the §4.2 wording ("never *silently* fall
  through") and INV-5.
- **`run.sh`** is changed from `exec … python app.py` to `exec … python
  launcher.py` so the from-source path gets the same tray + startup logic. Because
  `launcher.py` now owns browser-open (`_open_when_ready`), the standalone
  `xdg-open` line currently in `run.sh` (`run.sh:15`) is **removed** in the same
  change — otherwise `./run.sh` would open the browser twice.
- The **already-running second-launch** check (`_port_is_serving` → open browser
  → exit) is unchanged: the tray belongs to the first instance only; a second
  launch never creates a second icon.

### Menu action semantics

- **Open** → `webbrowser.open('http://127.0.0.1:{port}')`.
- **Restart** → reuse the CL-0046 mechanism in `server_control.py` (spawn a fresh
  detached process via `subprocess.Popen(..., start_new_session=True)` — `close_fds`
  is left at Popen's default of `True`, as the existing helper does — then
  `os._exit(0)`). No new respawn target is needed: `server_control` already
  respawns `os.path.abspath(sys.argv[0])`, so once `run.sh` routes through
  `launcher.py` (and the frozen entrypoint already is `launcher.py`), the restart
  is tray-capable automatically and brings up a fresh icon. The tray's Restart
  action therefore just calls `server_control.schedule('restart')` — no refactor,
  no duplicated spawn logic.
- **Quit** → `server.shutdown()` (unblocks `serve_forever`), `icon.stop()`, then
  return 0. Exits cleanly with no orphaned server thread.

## 6. Packaging / AppImage bundling

The whole point of a self-contained AppImage is that the tray works on a machine
that has **no** PyGObject/AppIndicator installed. The good news from the research:
**modern PyInstaller does the hard part automatically.** The custom
`hook-gi.repository.AppIndicator3.py` recipes on old forum threads are obsolete —
PyInstaller **6.3.0+ ships built-in hooks** for `gi.repository.AppIndicator3` and
`gi.repository.AyatanaAppIndicator3`, plus a maintained PyGObject (`gi`) hook
(updated through 6.13.0 for PyGObject 3.52) and GLib/Gio/DBus hooks [PyInstaller
CHANGES]. These collect the GObject-Introspection `.typelib` files that a frozen
app would otherwise fail to find ("Namespace AppIndicator3 not available"). We
pin PyInstaller to a current release (already unpinned to latest in CI) so these
hooks are present. **No hand-written GI hooks needed.**

What we still must arrange, in two places:

### 6.1 Build machine must have the GI/GTK/Ayatana stack installed

PyInstaller can only bundle libraries that exist on the **build** host. The Linux
release job runs on GitHub Actions `ubuntu-latest`, so `packaging/build-linux.sh`
(or the workflow step) must `apt-get install` the Ayatana stack before the
PyInstaller run:

```
gir1.2-ayatanaappindicator3-0.1   # the GI typelib pystray loads first
libayatana-appindicator3-1         # the shared lib (pulls libayatana-ido3, -indicator3)
libgirepository-1.0-1 gir1.2-glib-2.0   # GObject-Introspection core + typelibs
python3-gi                         # PyGObject — the `gi` module pystray imports
libgtk-3-0                         # appindicator backend links GTK3 at runtime
```

**Gotcha (the one the spike must nail):** `python3-gi` installs into the system
Python, but the release workflow's `actions/setup-python` step (`release.yml:19`,
pinned to 3.12) builds under a *different* interpreter that can't see it, and
PyGObject has **no pip wheel** (a `pip install PyGObject` needs `libcairo2-dev`,
`libgirepository1.0-dev`, `pkg-config` and a compiler). Resolving this is **not**
a matter of adding an `apt-get install` — it **reconfigures or replaces the
`setup-python` step**: either build with the distro's `python3` (which already has
`gi`) instead of the pinned setup-python, or create the build venv with
`--system-site-packages` so it inherits system `gi`. The interpreter choice in
`packaging/build-linux.sh` / the workflow is therefore explicitly **in scope** for
this change. The Linux-first spike (§10 step 1) confirms the exact incantation
before we touch the other OSes; this is the single highest-risk item.

### 6.2 PyInstaller spec additions

- `datas`: add the tray icon PNG as `('packaging/contact-list.png', 'packaging')`
  so it lands at `<bundle>/packaging/contact-list.png` and resolves at runtime via
  `resources.resource_path('packaging', 'contact-list.png')` (matching the
  `resource_path(*parts)` signature in `resources.py`); from source the same call
  finds it next to the code.
- Rely on the **built-in** `gi.repository.AyatanaAppIndicator3` hook; add
  `gi.repository.AyatanaAppIndicator3` (and `AppIndicator3` as a secondary) to
  `hiddenimports` only if the spike shows the automatic collection misses them.
- Windows/macOS specs are unaffected — pystray needs no GI stack there
  (`pyobjc-framework-Quartz` on macOS, nothing extra on Windows).

Because the AppImage bundles the collected `.so` files and typelibs, the **end
user installs nothing** — confirmed as the expected outcome for a bundled
GTK/AppIndicator tray app. openSUSE note: the target user's own machine ships the
*classic* `libappindicator3` (typelib `AppIndicator3`) rather than the Ayatana
fork, but this only matters for a *from-source* `./run.sh` run on their box, where
`gi` is already present system-wide; the AppImage carries its own Ayatana stack
regardless.

## 7. Error handling & graceful fallback

- **Tray unavailable** (import error, no display, backend init failure): catch,
  log one `INFO`/`WARNING` line ("system tray unavailable; running without an
  icon"), and fall back to **joining the server thread** — i.e. behave exactly as
  today. The app is fully functional without the icon.
- **Robust availability detection.** The research settled the right primitive:
  rather than hardcoding desktop-environment names (fragile — Electron's approach,
  criticised in the sources), query the **session DBus** for whether
  `org.kde.StatusNotifierWatcher` is owned, or read its read-only boolean
  `IsStatusNotifierHostRegistered` property — true only when a real tray host is
  present [KDE StatusNotifierWatcher XML; Electron issue #14635]. This is the
  clean way to catch the subtle failure mode where the appindicator icon
  *registers but never renders* because no host exists (which does **not** raise).
  **Pragmatics for v1:** because the tray runs on the main thread while the server
  runs on its own background thread, a silently-invisible icon is *not* a
  correctness problem — the server and browser still work. So the DBus pre-check
  is **defence-in-depth, not required**: we implement the cheap, decisive guards
  first (forced `appindicator` backend + try/except around `Icon.run()` → headless
  on any failure), and add the `IsStatusNotifierHostRegistered` DBus probe only if
  the spike shows a real "phantom icon" problem on a target desktop. Forcing the
  appindicator backend (§4.2) already removes the worst case — the `xorg` backend
  that "blocks forever on a tray that never appears" — so no watchdog timer is
  needed.
- **Restart spawn failure** → keep the current server serving (the CL-0046 helper
  already degrades this way).

## 8. Dependency & documentation changes

- `requirements.txt`: add `pystray>=0.19,<0.20` (major-capped per the deps-latest
  policy; 0.19.5 is current).
- **DESIGN.md §3 — bump the budget to 8 in all three places it is stated**, or
  they will drift out of sync: the cap prose (`DESIGN.md:41` "must stay under **8
  packages**" → "must stay at or under **8 packages**"), the running count
  (`DESIGN.md:56` "**Seven** runtime packages (under the 8-direct budget)" →
  "**Eight** runtime packages (at the 8-direct budget)"), and the build-tools note
  (`DESIGN.md:62` "the **< 8** runtime budget is unaffected" → "the 8-runtime
  budget is unaffected"). Add `pystray` to the runtime block, with the
  justification (tray icon = core desktop UX), mirroring the Pillow exception
  wording.
- **DESIGN.md §3 C-extension clause — a clarifying note, not a rewrite.** The
  clause (`DESIGN.md:41`) reads "No C-extension dependencies … with one authorised
  exception: Pillow." `pystray` itself is **pure Python**, so it does not add a
  C-extension *pip* dependency and the clause stands as written. Add one sentence
  noting that the Linux `appindicator` backend relies on the GI/GTK3 stack, which
  is a **build-time bundling artifact** carried in the AppImage (§6), not a
  declared pip dependency — so "one authorised exception: Pillow" remains accurate.
- **DESIGN.md §3 — platform backends:** note pystray's per-OS backends (Linux =
  Ayatana AppIndicator via `gi`/GTK3, bundled into the AppImage §6; macOS =
  `pyobjc-framework-Quartz`; Windows = nothing extra) as transitive / build-time.
  `python-xlib` ships transitively but the `xorg` backend is **never** selected
  (§4.2).
- **DESIGN.md §7.2 — add a carve-out for a *new* thread class, not a mirror of the
  CL-0046 one.** The existing §7.2 exceptions (`DESIGN.md:310`) are all
  **short-lived / one-shot** ("respawns a fresh child then exits milliseconds
  later"; browser-open "then does no further application work"). The tray model is
  materially stronger: a **long-lived** thread runs `server.serve_forever()` for
  the whole app lifetime, and serving HTTP *is* application work — exactly what
  §7.2's rule otherwise forbids. Document it explicitly as its own category ("tray
  owns the main thread ⇒ the HTTP server runs on one dedicated long-lived
  background thread; no shared mutable app state crosses threads beyond the server
  socket"), not as "analogous to CL-0046".
- **CHANGELOG.md** `[Unreleased]`: an Added entry.

## 9. Testing

- **Unit-test the three menu actions** with the server and `webbrowser` faked:
  Open calls `webbrowser.open` with the right URL; Quit calls `server.shutdown()`
  + `icon.stop()`; Restart calls the respawn helper (patched, never actually
  spawning — mirror the `PYTEST_CURRENT_TEST` guard in `server_control`).
- **Fallback path:** simulate pystray import/init failure and assert the launcher
  still serves headlessly without raising.
- **Packaging test:** add a new assertion in `tests/test_packaging.py` that reads
  `requirements.txt` and checks `pystray` is listed. (There is no existing
  dependency-assertion helper to reuse — `tests/test_packaging.py` currently tests
  `resource_path`, `_default_db_path`, `_auth_command`, and launcher
  single-instance/loopback behaviour only — so this is a fresh, self-contained
  test.)
- **Single-instance (INV-2):** the existing `test_launcher_single_instance_opens_browser`
  already asserts a second launch short-circuits to "open browser + exit" before
  building the app; confirm it still passes after the launcher restructure, so no
  second tray icon is ever created. No new test needed unless the restructure moves
  the guard.
- The icon **actually rendering** cannot be unit-tested (needs a live desktop),
  same as `webbrowser.open` is not tested. Covered instead by the manual spike
  below.

## 10. Implementation order (de-risk Linux first)

1. **Spike (throwaway):** build the AppImage with the §6.1 apt stack + forced
   appindicator backend and confirm the icon appears in the target KDE tray with a
   working Open/Restart/Quit menu, **before** building anything else. The one open
   unknown this must resolve is the §6.1 gotcha — making `gi` visible to the
   PyInstaller build Python on the CI runner. This is the single platform-risk gate.
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
- **INV-5:** if an icon is shown at all, it carries the full Open/Restart/Quit
  menu — we never render a degraded/menuless icon (guaranteed by forcing the
  `appindicator` backend and falling back to headless rather than to `xorg`; §4.2).

## 11. Sources (deep-research pass `wf_0fe49d44-bb6`)

Primary sources underpinning §4/§6/§7 (24 confirmed claims / 21 sources total):

- freedesktop **StatusNotifierItem** spec — SNI is DBus-based, replaces XEmbed.
- KDE **StatusNotifierWatcher** DBus XML — `org.kde.StatusNotifierWatcher`,
  `IsStatusNotifierHostRegistered`, registration model.
- **pystray** usage docs + FAQ + CHANGES — backend order & `PYSTRAY_BACKEND`;
  xorg = "no menu except default action"; appindicator = all features bar default;
  Ayatana AppIndicator support since 0.19.0; forced-backend since 0.16.0.
- **PyInstaller** CHANGES — built-in `gi.repository.AppIndicator3` /
  `AyatanaAppIndicator3` hooks (6.3.0+); PyGObject hook current to 6.13.0.
- **libayatana-appindicator** README + Debian/Fedora package pages — GTK3
  dependency, KSNI integration, distro package names.
- GNOME **AppIndicator/KStatusNotifierItem Support** extension page — GNOME needs
  it for SNI/tray; supports GNOME 45–50.
- Electron #14635, pystray #174, Waybar #2437 — Wayland/X11 behaviour and the
  DBus-ownership availability check.
