# Deliver the tray icon everywhere, and stop opening the page by itself (CL-0057, CL-0060)

**Status:** spec draft (2026-08-06).
**Kind:** fix.
**Source:** ROADMAP CL-0057 (in-session finding, root cause corrected by the user
2026-08-06) and CL-0060 (user decision, 2026-08-06).

**Blocker for:** CL-0059 (a *visible* tray icon with working Open / Restart / Quit).

*Layman:* the icon near the clock will now appear whichever way you start the app,
and the app will stop throwing a browser tab at you on every launch — you open the
page when you want it, from that icon. The one exception is a desktop with no tray
at all, where the tab still opens, because otherwise there would be no way to reach
the app.

## 1. Goal

After this ships, starting Contact List any of the three supported ways — `./run.sh`
from source, an AppImage you built yourself with `packaging/build-linux.sh`, or a
downloaded release — puts a working tray icon in the system tray, and **no first
start opens a web browser**.

The two host-Python paths (`./run.sh` and a local build) reach that state by
borrowing the host's GI/GTK stack, so they need the §4.5 distro packages; where
those are absent the app still runs, headless, exactly as it does today (INV-7). A
**downloaded release needs nothing installed** — it carries its own bundled stack
(§4.5).

The page is then reached deliberately, three ways: the tray icon's *Open Contact
List* menu item; an external process manager, which opens `http://127.0.0.1:<port>`
from its own UI using the URL the launcher prints on startup; or typing the address.

Two narrow cases still open a browser, and both are the app answering a question
rather than volunteering: launching a **second** copy while one is already running
(a person asking to see the app — INV-5), and a start whose **tray failed to
appear**, where there would otherwise be no way in at all (INV-8, decision 6). A
start whose tray works opens nothing, which is the change this spec exists to make.

## 2. Problem

Two independent defects that happen to meet at the same question — *how does the
user get to the page?*

### 2.1 The tray icon only exists in CI-built releases (CL-0057)

`tray.py::run_tray` is complete and shipped, and `launcher.py::main` calls it. What
is missing is the library stack underneath it. `pystray` resolves to its
`pystray._appindicator` backend — `launcher.py::main` *defaults* it there with
`os.environ.setdefault('PYSTRAY_BACKEND', 'appindicator')` before `tray` is
imported, which an explicit user `PYSTRAY_BACKEND` still overrides. That backend
imports the `gi` module — PyGObject — which ships as a **distro package with no
binary wheel**: `pip install PyGObject` builds from source and needs
`libgirepository` development headers, `pkg-config` and a C compiler. (The symptom
is the familiar `ERROR: Could not build wheels for PyGObject`; see
https://github.com/gfduszynski/cm-rgb/issues/45 for a representative report — the
canonical statement is PyGObject's own installation docs, which the implementer
should cite in the README instead of that issue.) So the only practical route is
for the interpreter to see the system copy.

`pystray._appindicator` requires `Gtk 3.0`, then tries `AppIndicator3` **first** and
falls back to `AyatanaAppIndicator3` — an order §4.3's pre-flight must mirror
exactly, or it rejects a host on which the tray would have worked.

Exactly one place arranges that, and it is not a packaging script:
`.github/workflows/release.yml` apt-installs the GI/Ayatana stack and then builds
inside `python3 -m venv --system-site-packages build-venv`, exporting
`PYTHON=build-venv/bin/python`.

Neither non-CI path does:

1. **From source.** `run.sh` creates its venv with a bare `python3 -m venv`, so
   `gi` is invisible to it. `launcher.py::main`'s tray call raises `ImportError`,
   the graceful fallback in the same function (`2026-07-12-system-tray-icon.md`
   INV-3) logs *"system tray unavailable or failed"* at INFO, and the app serves
   headless with no icon. Confirmed on an unmodified tree.
2. **Local AppImage.** `packaging/build-linux.sh` contains no
   `--system-site-packages` at all; its interpreter search is
   `for c in ./venv/bin/python python3 python`, which finds the same gi-less
   `./venv` that `run.sh` built. The build **exits 0** while logging
   `ERROR: Hidden import 'gi.repository.DBus' not found`, and the resulting
   AppImage serves normally, registers no tray item, and writes the same
   `ImportError` to `~/.config/contact-list/contact-list.log`. Verified against a
   built artefact, not inferred.

The fallback is graceful by design, which is precisely why this went unnoticed for
two releases: nothing fails, an icon simply never appears.

### 2.2 The app opens a browser on every start (CL-0060)

`launcher.py::main` starts a daemon thread running `launcher.py::_open_when_ready`,
which polls the loopback port and calls `browser.open_url` as soon as it accepts a
connection. This fires on **every** start that binds — including one driven by an
external process manager, and including a start whose whole purpose was to sit in
the tray. The user's position (2026-08-06): *"I don't want the site automatically
opened. That is why I wanted the tray icon or LWSM to be able to open the page."*

This is the same complaint as §2.1 seen from the other side: the automatic tab is
standing in for a tray icon that never arrives. Fixing either alone leaves the app
worse — remove the tab before the icon works and there is no way in at all.

## 3. Scope decisions (agreed with the user)

| # | Decision | Who, when |
|---|---|---|
| 1 | Fix CL-0057 by making the *runtime* interpreters gi-capable — `--system-site-packages` in both `run.sh` and `packaging/build-linux.sh` — and document the distro prerequisite. | User, 2026-08-06, choosing over "declare the tray release-build-only". |
| 2 | Do **not** make the graceful tray fallback (`2026-07-12-system-tray-icon.md` INV-3) louder. It stays an INFO log. | User, 2026-08-06, explicitly declining the "do both" option. |
| 3 | The **unconditional** startup auto-open is removed outright, not suppressed behind a flag. A start whose tray comes up opens nothing. (Decision 6 below adds the one exception, agreed later the same day.) | User, 2026-08-06. |
| 4 | The single-instance hand-off keeps opening the browser **when the port came from the default chain** (`CONTACT_LIST_PORT` → 5002): launching a second time while one is serving opens the page and exits 0. Where `PORT` named the port it still exits non-zero opening nothing, unchanged from CL-0056. *"I agree on 1, it should only allowed to have one instance running at a time."* | User, 2026-08-06. |
| 5 | The app's own pinned dependencies must still resolve to the venv, not to distro-managed copies. | Author, 2026-08-06 — see §4.2; §8 records the alternative. |
| 6 | **When the tray fails to come up, the browser opens after all** — the auto-open survives as a *fallback*, not as a startup behaviour. Where there is no icon to click, the alternative is an app the user cannot reach at all (§6). A tray deliberately skipped via `LWSM_MANAGED` is **not** a failure and opens nothing. | User, 2026-08-06, after the review surfaced the unreachable-app case. |

**A consequence worth stating, because it deletes work.** CL-0060's open problem was
*"if a managed start must not open a browser, it needs its own signal — not
`LWSM_MANAGED`, which is unauthenticated and trivially forged."* Decisions 3 and 6
together dissolve it. The managed path returns from `main` **before** the tray block
(`launcher.py::main`, unchanged), so it never reaches either the deleted startup open
or decision 6's fallback: a managed server opens nothing without anything having to
suppress it. **No new environment variable or flag is introduced**, and
`LWSM_MANAGED` keeps gating exactly one thing — whether the tray icon is shown.
INV-9 locks that in, deliberately using a *failing* tray stub so the test proves the
managed branch returns early rather than merely passing through a working tray.

## 4. Design

### 4.1 `run.sh` — a gi-capable venv, and a one-time rebuild of the stale one

`include-system-site-packages` is fixed when a venv is created and cannot be
toggled afterwards; the existing `venv/pyvenv.cfg` in every current clone says
`false`. So the flag alone would only help fresh checkouts. `run.sh` detects the
stale setting and rebuilds once.

**This block replaces `run.sh`'s existing "Create venv if missing" block** (the
`if [ ! -d "$VENV_DIR" ]` that currently holds a bare `python3 -m venv`); it is not
added alongside it. The per-launch `pip install -r requirements.txt` on the line
below stays exactly as it is.

```bash
# The tray icon's appindicator backend imports `gi` (PyGObject), a distro package
# with no binary wheel — so the venv must be able to see the system one.
# Two ways an existing venv can be unusable, and neither is "the directory is
# missing": include-system-site-packages is fixed at creation so a venv predating
# this change can never gain it, and a venv whose base interpreter was removed by a
# distro upgrade still looks present while being unable to run at all.
if [ -d "$VENV_DIR" ] && {
       ! grep -q '^include-system-site-packages = true' "$VENV_DIR/pyvenv.cfg" 2>/dev/null ||
       ! "$VENV_DIR/bin/python" -c '' 2>/dev/null
   }; then
    echo "Rebuilding venv so the tray icon can find the system GTK libraries..."
    rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
    # Force OUR pinned deps into the venv even where the distro already satisfies
    # the range — see §4.2. One-time cost; the per-launch sync below stays a no-op.
    "$VENV_DIR/bin/pip" install --quiet --ignore-installed -r "$APP_DIR/requirements.txt"
fi
```

Both halves of the guard were executed before being written here. `"$VENV_DIR/bin/python" -c ''`
exits 0 on a healthy venv and non-zero on one whose `pyvenv.cfg` and `bin/python`
were repointed at an absent interpreter — the 3.13 → 3.14 case of §6.

**Linux only in effect.** `run.sh` is also the from-source path on macOS, where
`--system-site-packages` would expose whatever the system or Homebrew Python
carries and reopen §4.2's shadowing question. The `--ignore-installed` step closes
it there for the same reason it does on Linux, and macOS needs no GI stack at all
(`pystray` selects a native backend), so the change is inert rather than harmful.
No macOS packaging change is in scope (§9).

### 4.2 Why `--ignore-installed` at creation

`--system-site-packages` makes pip treat distro packages as already installed. On
this openSUSE machine the system Python carries Flask 3.1.3 and Pillow 12.3.0 —
both named directly in `requirements.txt` — plus Jinja2 3.1.6 and Werkzeug 3.1.8,
which arrive transitively via Flask. All four satisfy what the resolver asks for, so
a plain `pip install -r requirements.txt` into such a venv **installs none of them**
and the app silently runs on distro-managed copies. Measured 2026-08-06: after
`pip install -r requirements.txt` into a `--system-site-packages` venv,
`ls <venv>/lib64/python3.13/site-packages` contained `pystray`, `phonenumbers` and
the Google stack but no `flask`, `PIL`, `jinja2` or `werkzeug`.

That is a real hazard on two counts: a distro upgrade could change app behaviour
with no repo change, and a locally built AppImage would bundle different libraries
than CI's, since CI's ubuntu runner has no system Flask to shadow with.

`--ignore-installed` at creation time fixes it without recurring cost. Measured on
the same venv afterwards:

```
flask  -> <venv>/lib64/python3.13/site-packages/flask/__init__.py
PIL    -> <venv>/lib64/python3.13/site-packages/PIL/__init__.py
gi     -> /usr/lib64/python3.13/site-packages/gi/__init__.py
```

(`lib64` is the real directory on this distro; `lib` is a symlink to it, so both
spellings resolve.) `gi` is still borrowed — it is not in `requirements.txt`, so
`--ignore-installed` never touches it — and a subsequent plain
`pip install -r requirements.txt` completed in 0.68 s as a no-op, preserving
`run.sh`'s per-launch budget.

**The known limit, stated rather than papered over.** `--ignore-installed` runs
only at venv creation, so a dependency **added to `requirements.txt` later** is
resolved by the ordinary per-launch `pip install`, which will borrow a
distro-supplied copy if one already satisfies it. The remedy is
`rm -rf venv && ./run.sh`, and INV-2's *breaks when* clause carries the case. Doing
it per-launch instead was rejected in §8 on cost.

**CI is unaffected in both directions.** `local-ci.sh` builds its own per-Python
environments under `.ci-venvs/`, explicitly "separate from the project's `./venv`
used to run the app", and the release workflow makes its own `build-venv`. Nothing
in §4.1 changes what either resolves.

### 4.3 `packaging/build-linux.sh` — build under a gi-capable interpreter

The script's interpreter search (`PY="${PYTHON:-}"`, else the first of
`./venv/bin/python python3 python`) stays, and CI's `PYTHON=` export keeps
overriding it. What changes is that when the search lands on `./venv/bin/python`,
that venv is now gi-capable by §4.1. The script gains a pre-flight that fails loudly
rather than producing a tray-less AppImage that exits 0.

**Insertion point:** immediately after the `$PY` fallback loop closes and before the
`TOOLS=` block that begins the appimagetool/runtime downloads. That is the only
position satisfying both constraints — `$PY` must already be resolved, and the probe
must run before the script spends time on ~100 MB of downloads it would then throw
away.

```bash
# PyInstaller can only bundle what the BUILD interpreter can import. Without this
# the build "succeeds" while logging "Hidden import 'gi.repository.DBus' not found"
# and ships an AppImage with no tray icon (CL-0057).
# The probe MIRRORS every require_version() pystray actually makes (§4.3.1) — not
# just the indicator one. DBus is the typelib CL-0052 already shipped a fix for
# (commit 3c817fc), and it is the one the error message above names.
if [ -z "$PY" ]; then
  echo "error: no Python interpreter found (tried \$PYTHON, ./venv/bin/python, python3, python)." >&2
  exit 1
fi
if ! "$PY" -c "import gi
for ns, ver in (('Gtk','3.0'), ('Gio','2.0'), ('DBus','1.0')): gi.require_version(ns, ver)
try: gi.require_version('AppIndicator3','0.1')
except ValueError: gi.require_version('AyatanaAppIndicator3','0.1')" 2>/dev/null; then
  echo "error: $PY cannot load the GI typelibs pystray needs — the AppImage would have no tray icon." >&2
  echo "       Install the GI stack (see README) and rebuild ./venv via ./run.sh." >&2
  exit 1
fi
```

### 4.3.1 The typelibs pystray requires — the authoritative list

Taken from the installed package, not from memory
(`grep -rn require_version venv/lib/python3.13/site-packages/pystray/`):

| Namespace | Version | Where pystray asks for it |
|---|---|---|
| `Gtk` | 3.0 | `_appindicator.py`, `_gtk.py`, `_util/gtk.py` |
| `Gio` | 2.0 | `_util/notify_dbus.py` |
| `DBus` | 1.0 | `_util/notify_dbus.py` |
| `AppIndicator3` **or** `AyatanaAppIndicator3` | 0.1 | `_appindicator.py` — Ayatana is the fallback |

`DBus` and `Gio` are easy to miss because they are reached through
`_util/notify_dbus.py` rather than the backend module, and missing `DBus` is
exactly what made the tray silently fall back to headless on KDE during CL-0052
(*"ValueError: Namespace DBus not available"*, fixed in commit `3c817fc` by adding
`gi.repository.DBus` to the PyInstaller hidden imports). A pre-flight that probes
only the indicator namespace would pass on a host that still cannot run the tray.

Executed before being written here: the full four-namespace probe exits 0 under a
`--system-site-packages` venv on this machine (resolving the indicator to
`AyatanaAppIndicator3`, `AppIndicator3` being absent), and non-zero under the
current gi-less `./venv`. `gi.require_version` alone is sufficient to catch a
missing typelib — it raises `ValueError: Namespace <X> not available` without any
`from gi.repository import`, which is why `import gi` on its own would not do
(INV-6's *breaks when*).

The empty-`$PY` guard matters because the search loop can end with `PY` unset on a
machine with no `python3` at all, where `"$PY" -c …` would otherwise fail with a
confusing "command not found" rather than the real cause.

This is the one place the design deliberately *stops being graceful*: a missing
icon at runtime is a degraded app, but a release artefact built without one is a
defect that ships. **It gates the release job too**, since the workflow runs this
same script — CI passes it because its `build-venv` is created with
`--system-site-packages` on a runner where the apt step installed the stack.

### 4.4 `launcher.py` — remove the startup auto-open

Delete `_open_when_ready` and the module constant `_OPEN_DEADLINE_S`, and delete the
`threading.Thread(target=_open_when_ready, …)` start in `main`. The `import time` at
module scope becomes orphaned — `time.monotonic` and `time.sleep` are used nowhere
else in the file — and is removed with it.

**The open moves into the tray-failure branch** (decision 6). One line, inside the
existing `except` that already handles a tray that could not start:

```python
    try:
        import tray
        tray.run_tray(server, port)  # blocks on the main thread until Quit
    except Exception:
        logging.info(
            'system tray unavailable or failed; running without an icon', exc_info=True
        )
        # No icon means no way in — open the page rather than leave a running
        # server the user cannot reach (decision 6). A tray skipped on purpose via
        # LWSM_MANAGED returns above and never reaches here.
        open_url(f'http://127.0.0.1:{port}')
        server_thread.join()
        return 0
```

**No polling is needed here, which is why `_open_when_ready` goes rather than
moves.** `make_server` binds the socket in its constructor — the existing comment in
`main` says so, and it is why a bind failure is caught there — so by the time
control reaches the tray branch the listener is already up and a browser's
connection waits in the accept backlog. The 15-second poll existed only because the
old call site ran concurrently with startup.

Two consequences worth stating, because they are what make this cheap:

- **Every browser-open in `main` is now on the main thread.** The hand-off open
  already was; this one is too. Nothing is left on a daemon thread, so the
  swallowed-assertion and race hazards that dogged the old design are gone, and the
  tests in §7 need neither a sleep nor a thread-safe recorder.
- **`LWSM_MANAGED=1` still opens nothing.** It returns from `main` *before* the tray
  block, so a managed server neither shows an icon nor opens a page — unchanged from
  CL-0056, and still the only thing that variable gates.

Everything else in `main` is untouched, and three things are explicitly preserved:

- the already-serving hand-off, which keeps its `browser.open_url` call and its
  `PORT`-explicit failure branch (CL-0056);
- the `LWSM_MANAGED` tray gate, still governing the icon and nothing else;
- the graceful tray fallback (`2026-07-12-system-tray-icon.md` INV-3, restated here
  as INV-7), still INFO, still joining the server thread.

`browser.open_url` stays imported — the hand-off uses it. `tray.py` is not touched
at all; its *Open Contact List* item already calls `open_url`, and it becomes the
primary way to reach the page.

### 4.5 The distro prerequisite

Documented in README beside the run instructions, for the two distro families the
project has evidence for:

**This applies to the two paths that use the host's Python — `./run.sh` from source
and a locally built AppImage. A downloaded release needs none of it**: the CI build
bundles the GI/GTK stack into the AppImage, which `DESIGN.md` §3 states as the
reason pystray does not count against the C-extension ban ("its Linux appindicator
backend relies on a GI/GTK3 stack that is a **build-time bundling artifact carried
in the AppImage** (§15), not a declared dependency"). Getting this scope wrong in
the README would tell every release downloader to install packages they do not need.

Each namespace of §4.3.1 has to be satisfiable. On openSUSE, verified by resolving
each typelib to its owning package with `rpm -qf /usr/lib64/girepository-1.0/<NS>.typelib`:

| Namespace | openSUSE package |
|---|---|
| PyGObject itself | `python3XX-gobject` |
| `Gtk-3.0` | `typelib-1_0-Gtk-3_0` |
| `Gio-2.0` | `typelib-1_0-Gio-2_0` |
| `DBus-1.0` | `girepository-1_0` |
| `AyatanaAppIndicator3-0.1` | `typelib-1_0-AyatanaAppIndicator3-0_1` (+ `libayatana-appindicator3-1`) |

`python3XX-gobject` carries openSUSE's interpreter version in its name — today
`python313-gobject`; a machine on a newer system Python needs the matching one, so
the README wording must not hard-code the digits.

**Debian/Ubuntu: use the list the release workflow already proves works** —
`python3-gi gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1
libgirepository-1.0-1 gir1.2-glib-2.0 libgtk-3-0`. Note that `libgtk-3-0` is the
shared library, not the `Gtk-3.0` **typelib** that `gi.require_version('Gtk','3.0')`
needs; CI works today because the Ayatana GI package pulls the Gtk and freedesktop
typelibs in transitively. That is a working arrangement resting on someone else's
dependency graph, so the README should name `gir1.2-gtk-3.0` explicitly alongside
it. **This row was not verified on a Debian machine** — unlike the openSUSE table
above, it is inferred from `release.yml` plus the transitive argument, and the
implementer should confirm it on Ubuntu before it reaches the README.

Absent these packages, §4.1 still works and the app still runs — it falls back to
headless exactly as today (INV-7). Only `build-linux.sh` treats their absence as
fatal, and only at build time.

## 5. Invariants

- **INV-1** — A venv created by `run.sh` can load **every** GI namespace pystray
  requires (§4.3.1), on a machine with the §4.5 packages installed.
  *Test:* the §4.3 probe run against the app venv —
  `./venv/bin/python -c "import gi
  for ns, ver in (('Gtk','3.0'), ('Gio','2.0'), ('DBus','1.0')): gi.require_version(ns, ver)
  try: gi.require_version('AppIndicator3','0.1')
  except ValueError: gi.require_version('AyatanaAppIndicator3','0.1')
  print('ok')"` → `ok`. (Not runnable until §4.1 lands; the identical probe against a
  hand-made `--system-site-packages` venv succeeded on 2026-08-06, resolving the
  indicator to `AyatanaAppIndicator3`.)
  *Breaks when:* the venv is created without `--system-site-packages`, or predates
  this change and the §4.1 rebuild guard fails to fire. **Testing `AyatanaAppIndicator3`
  alone would also break it on a host carrying only the older `AppIndicator3`
  typelib** — the same trap §4.3's probe avoids, which is why this clause mirrors
  that probe rather than naming one namespace.

- **INV-2** — The app's own runtime dependencies resolve inside the venv, not to
  the system Python, despite `--system-site-packages`.
  *Test:* `./venv/bin/python -c "import flask; print(flask.__file__)"` → a path
  under `./venv/`, not under `/usr/`.
  *Breaks when:* the venv is created without `--ignore-installed` on a distro whose
  system Python already satisfies a dependency — Flask and Pillow are named
  directly in `requirements.txt`, Jinja2 and Werkzeug arrive transitively, and all
  four are satisfied by the system Python on this machine today. **Also breaks for
  any dependency added to `requirements.txt` after the venv was built**, since the
  per-launch `pip install` runs without `--ignore-installed`; remedy is
  `rm -rf venv && ./run.sh` (§4.2).

- **INV-3** — `run.sh` rebuilds a venv that is unusable for either reason — its
  `pyvenv.cfg` lacks `include-system-site-packages = true`, or its base interpreter
  no longer runs — exactly once, and the rebuilt venv then satisfies INV-1.
  *Test:* two manual recipes, one per branch — the invariant has two halves and a
  recipe for one proves nothing about the other.
  (a) marker branch: `sed -i 's/^include-system-site-packages = true/include-system-site-packages = false/' venv/pyvenv.cfg`, then `./run.sh`; the rebuild message appears, and a second `./run.sh` does not repeat it.
  (b) orphaned-interpreter branch: `ln -sf /usr/bin/python3.99 venv/bin/python`, then `./run.sh`; the same rebuild message appears.
  (Both edit the working venv on purpose; the same `./run.sh` restores it by rebuilding, so neither needs a cleanup step.)
  *Breaks when:* the guard tests for the venv directory only, so an existing
  gi-less venv is reused forever; or it tests `pyvenv.cfg` only, so a venv orphaned
  by a system-Python upgrade keeps its `true` marker and is never rebuilt (§6).

- **INV-4** — A server start whose **tray comes up** opens no browser. This is the
  headline behaviour change: the unconditional startup open is gone.
  *Test:* `tests/test_launcher_no_autoopen.py::test_start_with_working_tray_opens_no_browser` —
  stub `_port_is_serving` → `False`, `create_app`, `werkzeug.serving.make_server` →
  a fake handle, and `tray.run_tray` → a no-op (a tray that starts and is then
  quit). Record `launcher.open_url` into a list; assert `main()` returns 0 and the
  list is empty. (Not runnable until §4.4 lands.)
  *Breaks when:* an unconditional browser-open is reintroduced on the binding path —
  including one added "just for the frozen build" or behind a new environment
  variable.

  **`tray.run_tray` must be stubbed**, here and in INV-9's test. With §4.4's
  auto-open thread gone, `main()` falls through to `tray.run_tray(server, port)`,
  which blocks the calling thread until Quit — so on exactly the gi-capable machine
  §4.1 creates, an unstubbed test hangs instead of passing. Every existing sibling
  in `tests/test_packaging.py` stubs it for this reason.

- **INV-5** — The single-instance hand-off still opens the browser and exits 0 when
  the port came from the default chain, and still exits non-zero opening nothing
  when `PORT` named it.
  *Test:* `python -m pytest tests/test_packaging.py::test_launcher_single_instance_opens_browser tests/test_port.py::test_busy_port_with_explicit_port_fails_without_a_browser -q`
  → `2 passed`.
  *Breaks when:* INV-4 is implemented by removing `open_url` from `main` wholesale
  rather than from the startup path only — the likeliest way to overshoot.

- **INV-6** — A local `bash packaging/build-linux.sh` either produces an AppImage
  whose tray works, or fails non-zero naming the missing import. It never exits 0
  with `Hidden import 'gi.repository.DBus' not found` in its output.
  *Test:* manual recipe — create a bare venv (`python3 -m venv /tmp/bare`), run
  `PYTHON=/tmp/bare/bin/python bash packaging/build-linux.sh` and confirm a non-zero
  exit naming the missing typelib; then run it under `./venv/bin/python` and confirm
  exit 0 with no `Hidden import` line. (A bare venv, not an interpreter flag —
  `build-linux.sh` invokes `"$PY" -m PyInstaller` quoted, so a flag embedded in
  `$PYTHON` would fail as command-not-found rather than as the gi-less case.)
  *Breaks when:* the pre-flight checks only `import gi` without a
  `gi.require_version(...)` — `gi` alone imports fine on a machine with PyGObject
  but no typelibs, which is exactly the half-installed state that produced a silent
  tray-less build; or it checks the indicator namespace only, in which case a host
  missing `DBus` or `Gio` passes the probe and **still** emits the
  `Hidden import 'gi.repository.DBus' not found` line this invariant forbids
  (§4.3.1); or it checks `AyatanaAppIndicator3` only, rejecting a host that carries
  the older `AppIndicator3` typelib pystray prefers (§2.1).

- **INV-7** — With the §4.5 packages absent, the app still starts and serves; it
  logs the tray failure at INFO and runs headless. The process does not crash and
  the exit code is 0. The INFO record **carries a traceback by design** —
  `launcher.py::main`'s fallback logs with `exc_info=True`, so from source the
  traceback reaches stderr and when frozen it reaches
  `~/.config/contact-list/contact-list.log`. That is diagnostic output, not a crash.
  *Test:* `python -m pytest tests/test_packaging.py::test_launcher_falls_back_to_headless_when_tray_fails -q`
  → `1 passed`.
  *Breaks when:* the tray import is hoisted out of the `try` in `launcher.py::main`,
  or the pre-flight of §4.3 is copied into the runtime path — it belongs to the
  build only.

- **INV-8** — A server start whose **tray fails** does open the browser, so a
  running app is never unreachable (decision 6).
  *Test:* `tests/test_launcher_no_autoopen.py::test_tray_failure_opens_browser` —
  same stubs as INV-4 except `tray.run_tray` raises `ImportError`; assert `main()`
  returns 0 and the recorded URL is `http://127.0.0.1:<port>`.
  *Breaks when:* the open is placed before the `try` rather than inside the
  `except`, which would reintroduce the unconditional open INV-4 forbids; or the
  `except` returns before opening.

- **INV-9** — A start with `LWSM_MANAGED=1` opens no browser **whether or not a tray
  would have worked**, because a deliberately skipped tray is not a failed one.
  *Test:* `tests/test_launcher_no_autoopen.py::test_managed_start_opens_no_browser` —
  set `LWSM_MANAGED=1`, stub as INV-4 but make `tray.run_tray` raise; assert
  `main()` returns 0 and nothing was recorded. The raise proves the managed path
  returns before the tray block rather than merely passing through it.
  *Breaks when:* the fallback open is moved above the `LWSM_MANAGED` return, or the
  managed branch is rewritten to fall through to the tray block. Either turns a
  managed server into one that sprays a browser tab on every start — the outcome
  CL-0056 and CL-0060 both exist to prevent.

## 6. Failure modes

| Assumption | When it breaks | Behaviour |
|---|---|---|
| The system Python has `gi` + the typelib | Packages not installed | Tray import fails → INV-7 headless fallback, INFO log. App works, no icon. |
| The venv's base Python matches the system one | System Python upgrades 3.13 → 3.14 and the old interpreter is removed | The venv directory still exists and its `pyvenv.cfg` still says `include-system-site-packages = true`, so **neither the marker check nor the venv-missing branch fires**. §4.1's second guard — `"$VENV_DIR/bin/python" -c ''` — is what catches this: the orphaned interpreter fails to run, the venv is rebuilt, and `--system-site-packages` then points at the new version's site-packages. |
| A distro package shadows a pinned dep | Only if §4.2's `--ignore-installed` is skipped | INV-2 fails; the app runs on distro copies. This is the pre-fix behaviour, so it degrades to today rather than to broken. |
| The tray is the only way in | Tray fails on a desktop with no tray support at all (GNOME without an AppIndicator extension is the common case) | **The browser opens** (INV-8, decision 6). This is the case that made the fallback necessary: on a frozen windowed build `launcher.py::_emit` writes nothing — `packaging/contact-list.spec` sets `console=False`, so `sys.stdout`/`sys.stderr` are `None` — meaning the `Listening on http://127.0.0.1:<port>` line reaches no one. Without the fallback the user would have no icon, no tab and no visible address: a running server that cannot be reached. |
| The user wants the page and the tray is fine | Any normal start | Nothing opens. The tray icon's *Open Contact List*, an external manager, or a second launch (INV-5) are the ways in. |
| `build-linux.sh` runs where `./venv` was never built | Fresh clone, build before first run | Interpreter search falls through to the system `python3`, which on this machine passes §4.3's probe (it owns the typelibs) and then fails at `"$PY" -m PyInstaller` with `No module named PyInstaller` — the system Python has neither PyInstaller nor Flask. Passing the pre-flight is not the same as being able to build. Remedy: run `./run.sh` once first, or export `PYTHON=`. |

## 7. Tests

Two edits to the existing suite are mandatory, and only the first fails loudly.

**1. Remove the four `launcher._open_when_ready` monkeypatch sites** —
`tests/test_port.py` (1) and `tests/test_packaging.py` (3), counted with
`grep -o _open_when_ready tests/*.py | wc -l` → `4`. Left in place they raise
`AttributeError` from `monkeypatch.setattr`, so the omission fails loudly at test
time rather than passing silently.

**2. Stub `launcher.open_url` in every test that drives the tray to failure — this
one fails SILENTLY and noisily in the wrong sense.** Decision 6 puts a real
`open_url` call inside the `except` branch, so any test that makes `tray.run_tray`
raise and does not stub `open_url` will **launch an actual web browser** on every
suite run. `grep -n run_tray tests/*.py` finds four sites; the one that raises and
does not stub `open_url` is
`tests/test_packaging.py::test_launcher_falls_back_to_headless_when_tray_fails`
(it monkeypatches `tray.run_tray` to a `boom` that raises `RuntimeError`). Nothing
in the assertion notices — the test still returns 0 and still passes — so this is
caught by reading the diff, not by the suite. Add the stub there as part of this
change; the two `tests/test_port.py` sites already carry an `open_url` patch, and
`tests/test_packaging.py`'s other site stubs `run_tray` to a no-op and never reaches
the branch.

| Invariant | Test | Status |
|---|---|---|
| INV-4 | `tests/test_launcher_no_autoopen.py::test_start_with_working_tray_opens_no_browser` | new |
| INV-8 | `tests/test_launcher_no_autoopen.py::test_tray_failure_opens_browser` | new |
| INV-9 | `tests/test_launcher_no_autoopen.py::test_managed_start_opens_no_browser` | new |
| INV-5 | `tests/test_packaging.py::test_launcher_single_instance_opens_browser`, `tests/test_port.py::test_busy_port_with_explicit_port_fails_without_a_browser` | exists, must keep passing |
| INV-7 | `tests/test_packaging.py::test_launcher_falls_back_to_headless_when_tray_fails` | exists, must keep passing |

**The three new tests run entirely on the main thread**, which is what makes them ordinary
tests. Decision 6 put the surviving open inside the tray-failure `except`, so no
browser-open happens on a daemon thread any more. That removes two hazards the
poll-thread design carried: an assertion raised inside an `open_url` stub would have
been swallowed by `threading.excepthook` and the run would stay green (verified
2026-08-06 by raising in a daemon thread and watching the parent survive), and the
open raced `main()`'s return. Neither applies now. Record `open_url` into a list and
assert on it after `main()` returns; no sleep, no recorder locking.

**Seeing INV-4 fail against pre-fix code** is a one-time author step and needs the
`_port_is_serving` stub to return `False` first (the single-instance check) and
`True` afterwards, so the pre-fix poll thread finds a listener and opens. With the
sibling tests' constant `False`, pre-fix code never reaches `open_url` and the test
passes vacuously. Record the red run's output in the commit message; a test that has
only ever been green is a test nobody has seen work.

New tests go inside `tests/conftest.py`'s existing protection — it sets
`QT_QPA_PLATFORM=offscreen` and `SECRET_KEY` via `os.environ.setdefault` before any
test module loads, because importing `config` with `SECRET_KEY` unset writes a real
secret into `~/.config/contact-list`.

Baseline before this change: `400 tests collected` (`pytest tests/ -q --collect-only`).

## 8. Alternatives considered (and rejected)

- **Declare the tray a release-build-only feature** and make the INV-3 fallback say
  so out loud. Rejected by the user, 2026-08-06: it fixes the honesty of the message
  without fixing the feature, and leaves CL-0059 permanently unshippable from source.
- **`pip install PyGObject` into the isolated venv.** No binary wheel exists; it
  builds from source against `libgirepository` headers, needs a compiler, and would
  add a direct dependency against DESIGN.md §3's budget of <8. It also would not
  help: the GTK3 and AppIndicator *typelibs* are distro files regardless.
- **Symlink only `gi` into an otherwise-isolated venv.** Surgical, and it would keep
  INV-2 for free — but it is non-idiomatic, ABI-couples the venv to the exact system
  Python build, and diverges from what `release.yml` already does. Matching CI's
  mechanism is worth more than the elegance.
- **`--ignore-installed` on every launch** rather than at creation. It would close
  §4.2's later-added-dependency hole outright, but it reinstalls the full dependency
  tree on every single launch, defeating the idempotent per-launch sync `run.sh` is
  built around (measured: 0.68 s as a no-op today). Rejected on cost; the hole is
  documented in INV-2 with `rm -rf venv` as its remedy.
- **Suppress the auto-open only under an external manager.** This was CL-0060's
  original framing. Superseded by decision 3 — the user does not want it on any
  path, which is both simpler and avoids inventing the trustworthy signal
  `LWSM_MANAGED` could not be.

## 9. Out of scope

- Confirming a *visible* icon with working menu items on a stock desktop — that is
  CL-0059, which this unblocks.
- `tray.py`'s menu contents. Already shipped by CL-0052; not rebuilt.
- Windows and macOS packaging. Neither uses `gi`; `pystray` picks a native backend.
- Any change to `LWSM_MANAGED`'s meaning, or any new launch flag.
- CL-0058 — a stale citation of `2026-07-10-standalone-launchers-design.md` INV-6
  (the loopback-bind invariant) elsewhere in the docs. Unrelated to this spec's own
  INV-6, and not touched here.

## 10. Resource cost

No new runtime state and no new pip dependency — the DESIGN.md §3 budget is
untouched. Two costs, both one-time and both local:

1. **Rebuilding an existing `venv` once** — a full `pip install` of the dependency
   tree. Estimated at tens of seconds; not measured, because the figure depends on
   the pip cache state and nothing in this spec rests on it.
2. **The §4.5 distro packages — 2.5 MB installed**, measured on 2026-08-06 with
   `rpm -q --qf '%{SIZE}\n' typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 libayatana-indicator3-7 libdbusmenu-glib4 libdbusmenu-gtk3-4 libayatana-ido3-0_4-0 ayatana-indicator3-7-common python313-gobject | awk '{s+=$1} END {printf "%.1f MB\n", s/1048576}'`.
   That is the Ayatana chain plus PyGObject; `typelib-1_0-Gtk-3_0`,
   `typelib-1_0-Gio-2_0` and `girepository-1_0` were already present on this machine
   and are not counted.

The per-launch `pip install` stays a no-op, measured at 0.68 s.

## 11. What checks this

| Invariant | What catches a breach |
|------|----------------------|
| INV-1 | **nothing automated** — needs the real distro packages and a real venv; manual clause in §5, and CL-0059's acceptance re-checks it |
| INV-2 | **nothing automated** — asserting an import path inside CI's own venv would pass vacuously where no system Flask exists to shadow; manual clause in §5 |
| INV-3 | **nothing automated** — manual recipe in §5; a shell-level guard has no test harness in this project |
| INV-4 | `tests/test_launcher_no_autoopen.py::test_start_with_working_tray_opens_no_browser` |
| INV-5 | `tests/test_packaging.py::test_launcher_single_instance_opens_browser` + `tests/test_port.py::test_busy_port_with_explicit_port_fails_without_a_browser` |
| INV-6 | **nothing automated** — the AppImage build is not run in the test suite; the §4.3 pre-flight is itself the mechanical catcher at build time |
| INV-7 | `tests/test_packaging.py::test_launcher_falls_back_to_headless_when_tray_fails` |
| INV-8 | `tests/test_launcher_no_autoopen.py::test_tray_failure_opens_browser` |
| INV-9 | `tests/test_launcher_no_autoopen.py::test_managed_start_opens_no_browser` |

Nine invariants, four `nothing` rows. Three of the four (INV-1, INV-2, INV-3) are
honest limits of a Python test suite over shell and distro state; the fourth (INV-6)
is converted from "silent wrong output" to "loud failure" by §4.3, which is the best
available rung short of building an AppImage in CI on every push.

INV-8 and INV-9 are the rows worth noticing: both cover behaviour that appears only
when something *else* has already gone wrong, which is exactly the kind of path that
rots unnoticed. Both are real unit tests rather than manual clauses, so a later
refactor that hoists the open out of the `except` — or above the `LWSM_MANAGED`
return — fails the suite instead of shipping.

## 12. Cross-doc impact

- **README** — four claims that the browser opens automatically (the intro line, the
  "opens in your browser automatically" paragraph, the `run.sh` description, and the
  `launcher.py` file-map entry) become wrong and are corrected; §4.5's prerequisite
  table is added beside the Python-version requirement.
- **CLAUDE.md** — **no change needed.** The *Verifying a launch by hand* bullet
  already says "to prove a path opens *no* browser, you need it recorded, not merely
  unobserved", which is exactly the check this change makes routine. Listed here so
  a later reader knows it was considered rather than missed.
- **`launcher.py` module docstring** — responsibility 4 currently reads "open the
  browser once the socket is up, and run the system-tray icon on the main thread".
  The browser clause goes.
- **`run.sh` comment** — "launcher.py owns the tray + browser-open; no separate
  xdg-open here (it would open the browser twice)". The ownership clause **stays
  true** (the hand-off open still lives in `launcher.py`); what dies is the
  parenthetical double-open rationale, since a fresh `./run.sh` no longer opens
  anything. Reword rather than delete.
- **`docs/specs/2026-07-10-standalone-launchers-design.md`** — INV-4's "the browser
  is opened only after the socket accepts a connection" sentence is superseded.
  Annotated in place, never renumbered.
- **`docs/specs/2026-07-12-system-tray-icon.md`** — §6.1 is scoped to the build
  machine only; a pointer here records that the run machine needs the same stack.
- **CHANGELOG** — `Fixed` (tray icon now appears on from-source and locally built
  installs, not only CI releases) and `Changed` (a start no longer opens a browser
  when the tray comes up; it still opens one if the tray fails, so the app is never
  unreachable). The `Changed` entry must carry the exception — a flat "no longer
  opens a browser" would read as a bug the first time a user on a tray-less desktop
  sees a tab.
- **ROADMAP** — CL-0057 and CL-0060 flip to shipped; CL-0059 loses its blocker.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 2 | 2026-08-06 | 2 | 2 | 3 | 5 | 8 | All 18 verified, 0 unverified. 17 fixed; 1 surfaced to the user as a design decision and answered, becoming decision 6 + INV-8 + INV-9. Dimensions: dim 2×5, dim 4×4, dim 5×3, dim 10×3, dim 15×2, dim 7×1. Origin split: ~10 fix collateral from loop 1, ~8 draft defects. The decisive finding was **not a doc defect**: with the auto-open gone, a frozen windowed build whose tray fails has no icon, no tab and no visible URL (`_emit` writes nothing when `console=False`), i.e. an unreachable running app — the user chose to keep the open as a tray-failure fallback. That answer also removed the daemon thread entirely, dissolving loop 1's swallowed-assertion and race problems. Also corrected: §4.3's probe omitted `DBus`/`Gio` (the very typelibs CL-0052 shipped commit `3c817fc` for, and the one named in the error string INV-6 forbids), §1 applied the distro prerequisite to downloaded releases against `DESIGN.md` §3, INV-1 tested Ayatana-only while §4.3 accepted either indicator, and `test_launcher_falls_back_to_headless_when_tray_fails` would have launched a real browser on every suite run. Orchestrator error recorded: the loop-2 packet carried a stale 377-line count (the doc was 503), which both lanes flagged. |
| 1 | 2026-08-06 | 2 | 1 | 6 | 8 | 10 | All 25 verified, 0 unverified, all fixed. Dimensions: dim 2×6, dim 6×6, dim 4×4, dim 7×4, dim 5×2, dim 9×1, dim 10×1, dim 15×1. Two of the draft's own prescriptions were executed and found wrong: the §4.3 pre-flight checked `AyatanaAppIndicator3` only, but `pystray._appindicator` probes `AppIndicator3` first (would have failed a working host); and §4.1's rebuild guard missed a venv orphaned by a system-Python upgrade, which §6 wrongly called handled. Also corrected: an `INV-3`/`INV-6` label collision with borrowed invariants, INV-4's test contract omitting the `tray.run_tray` stub (would hang on exactly the machines this change creates), INV-4's pre-fix red run being vacuous, INV-7 claiming "no traceback" against `exc_info=True`, and a resource figure wrong by 6× (400 KB → measured 2.5 MB). |
