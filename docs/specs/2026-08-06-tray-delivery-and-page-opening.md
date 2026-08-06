# Deliver the tray icon everywhere, and stop opening the page by itself (CL-0057, CL-0060)

**Status:** spec draft (2026-08-06).
**Kind:** fix.
**Source:** ROADMAP CL-0057 (in-session finding, root cause corrected by the user
2026-08-06) and CL-0060 (user decision, 2026-08-06).

**Blocker for:** CL-0059 (a *visible* tray icon with working Open / Restart / Quit).

*Layman:* the icon near the clock will now appear whichever way you start the app,
and the app will stop throwing a browser tab at you on every launch — you open the
page when you want it, from that icon.

## 1. Goal

After this ships, starting Contact List any of the three supported ways — `./run.sh`
from source, an AppImage you built yourself with `packaging/build-linux.sh`, or a
downloaded release — puts a working tray icon in the system tray **on a machine
carrying the §4.5 distro packages**, and none of them opens a web browser. Where
those packages are absent the app still runs, headless, exactly as it does today
(INV-7).

The page is then reached deliberately, three ways: the tray icon's *Open Contact
List* menu item; an external process manager, which opens `http://127.0.0.1:<port>`
from its own UI using the URL the launcher prints on startup; or typing the address.
Launching a second copy while one is already running remains the one gesture that
opens the browser, because that is a person asking to see the app.

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
`libgirepository` development headers, `pkg-config` and a C compiler
(Source: https://github.com/gfduszynski/cm-rgb/issues/45). So the only practical
route is for the interpreter to see the system copy.

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
| 3 | No start of the server opens a browser. The startup auto-open is removed outright, not suppressed behind a flag. | User, 2026-08-06. |
| 4 | The single-instance hand-off keeps opening the browser **when the port came from the default chain** (`CONTACT_LIST_PORT` → 5002): launching a second time while one is serving opens the page and exits 0. Where `PORT` named the port it still exits non-zero opening nothing, unchanged from CL-0056. *"I agree on 1, it should only allowed to have one instance running at a time."* | User, 2026-08-06. |
| 5 | The app's own pinned dependencies must still resolve to the venv, not to distro-managed copies. | Author, 2026-08-06 — see §4.2; §8 records the alternative. |

**A consequence worth stating, because it deletes work.** CL-0060's open problem was
*"if a managed start must not open a browser, it needs its own signal — not
`LWSM_MANAGED`, which is unauthenticated and trivially forged."* Decision 3 dissolves
it: with no automatic open anywhere, there is nothing left to suppress. **No new
environment variable or flag is introduced**, and `LWSM_MANAGED` keeps gating exactly
one thing — whether the tray icon is shown — as `launcher.py::main` already does.

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

**Insertion point:** immediately after the `$PY` fallback loop and before
`bash packaging/make-icons.sh` / the `"$PY" -m PyInstaller` invocation — the
pre-flight needs `$PY` resolved and must run before any build work happens.

```bash
# PyInstaller can only bundle what the BUILD interpreter can import. Without this
# the build "succeeds" while logging "Hidden import 'gi.repository.DBus' not found"
# and ships an AppImage with no tray icon (CL-0057).
# The probe MIRRORS pystray._appindicator's own import order — Gtk 3.0, then
# AppIndicator3 with AyatanaAppIndicator3 as the fallback. Checking only Ayatana
# would fail a host carrying the older typelib, on which the tray works fine.
if [ -z "$PY" ]; then
  echo "error: no Python interpreter found (tried \$PYTHON, ./venv/bin/python, python3, python)." >&2
  exit 1
fi
if ! "$PY" -c "import gi; gi.require_version('Gtk','3.0')
try: gi.require_version('AppIndicator3','0.1')
except ValueError: gi.require_version('AyatanaAppIndicator3','0.1')" 2>/dev/null; then
  echo "error: $PY cannot load Gtk3 + an AppIndicator typelib — the AppImage would have no tray icon." >&2
  echo "       Install the GI stack (see README) and rebuild ./venv via ./run.sh." >&2
  exit 1
fi
```

Executed before being written here: the probe exits 0 under a
`--system-site-packages` venv on this machine, and non-zero under the current
gi-less `./venv`. `gi.require_version` alone is sufficient to catch a missing
typelib — it raises `ValueError: Namespace <X> not available` without any
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

| | Packages |
|---|---|
| openSUSE | `python3XX-gobject typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 typelib-1_0-Gtk-3_0` |
| Debian/Ubuntu | `python3-gi gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 libgtk-3-0 libgirepository-1.0-1 gir1.2-glib-2.0` |

`python3XX-gobject` carries openSUSE's interpreter version in its name — today
`python313-gobject`; a machine on a newer system Python needs the matching one, so
the README wording must not hard-code the digits. The GTK3 and
GObject-Introspection core entries are required because `pystray._appindicator`
does `gi.require_version('Gtk','3.0')` before it looks for any indicator typelib
(§2.1), matching the list `2026-07-12-system-tray-icon.md` §6.1 already gives for
the build machine. Installing the Ayatana package pulls most of the rest in as
dependencies — on this machine it brought `ayatana-indicator3-7-common`,
`libayatana-ido3-0_4-0`, `libdbusmenu-glib4`, `libayatana-indicator3-7` and
`libdbusmenu-gtk3-4` — but naming them explicitly is what makes the list
reproducible rather than lucky.

Absent them, §4.1 still works and the app still runs — it falls back to headless
exactly as today (INV-7). Only `build-linux.sh` treats their absence as fatal, and
only at build time.

## 5. Invariants

- **INV-1** — A venv created by `run.sh` can import `gi` and the Ayatana
  AppIndicator typelib, on a machine with the §4.5 packages installed.
  *Test:* `./venv/bin/python -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1'); from gi.repository import AyatanaAppIndicator3; print('ok')"`
  → `ok`. (Not runnable until §4.1 lands; the identical command against a
  hand-made `--system-site-packages` venv printed `ok` on 2026-08-06.)
  *Breaks when:* the venv is created without `--system-site-packages`, or predates
  this change and the §4.1 rebuild guard fails to fire.

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
  *Test:* manual recipe — `sed -i 's/^include-system-site-packages = true/include-system-site-packages = false/' venv/pyvenv.cfg`, then `./run.sh`; the rebuild message appears, and a second `./run.sh` does not repeat it. (The `sed` edits the working venv on purpose; the same `./run.sh` restores it by rebuilding, so no cleanup step is needed.)
  *Breaks when:* the guard tests for the venv directory only, so an existing
  gi-less venv is reused forever; or it tests `pyvenv.cfg` only, so a venv orphaned
  by a system-Python upgrade keeps its `true` marker and is never rebuilt (§6).

- **INV-4** — No path that starts the server opens a browser.
  *Test:* `tests/test_launcher_no_autoopen.py::test_server_start_opens_no_browser` —
  monkeypatch `launcher.open_url` to fail the test if called, and stub the whole
  startup path as the sibling tests do: `_port_is_serving`, `create_app`,
  `werkzeug.serving.make_server` → a fake handle, **and `tray.run_tray` → a no-op**.
  Assert `launcher.main()` returns 0. (Not runnable until §4.4 lands.)
  *Breaks when:* any browser-open is reintroduced on the binding path — including
  one added "just for the frozen build" or behind a new environment variable.

  **The `tray.run_tray` stub is not optional.** With §4.4's auto-open thread gone,
  `main()` falls through to `tray.run_tray(server, port)`, which blocks the calling
  thread until Quit — so on exactly the gi-capable machine §4.1 creates, an
  unstubbed test hangs instead of passing. Every existing sibling in
  `tests/test_packaging.py` stubs it for this reason. §7 covers how the pre-fix red
  run is obtained, which needs more than these stubs.

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
  but no indicator typelib, which is exactly the half-installed state that produced
  a silent tray-less build; or it checks `AyatanaAppIndicator3` only, rejecting a
  host that carries the older `AppIndicator3` typelib pystray prefers (§2.1).

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

## 6. Failure modes

| Assumption | When it breaks | Behaviour |
|---|---|---|
| The system Python has `gi` + the typelib | Packages not installed | Tray import fails → INV-7 headless fallback, INFO log. App works, no icon. |
| The venv's base Python matches the system one | System Python upgrades 3.13 → 3.14 and the old interpreter is removed | The venv directory still exists and its `pyvenv.cfg` still says `include-system-site-packages = true`, so **neither the marker check nor the venv-missing branch fires**. §4.1's second guard — `"$VENV_DIR/bin/python" -c ''` — is what catches this: the orphaned interpreter fails to run, the venv is rebuilt, and `--system-site-packages` then points at the new version's site-packages. |
| A distro package shadows a pinned dep | Only if §4.2's `--ignore-installed` is skipped | INV-2 fails; the app runs on distro copies. This is the pre-fix behaviour, so it degrades to today rather than to broken. |
| The tray is the only way in | Tray fails **and** the user does not know the URL | The `Listening on http://127.0.0.1:<port>` line that `launcher.py::main` prints on every binding start is the fallback, and the second-launch hand-off (INV-5) still opens the page. |
| `build-linux.sh` runs where `./venv` was never built | Fresh clone, build before first run | Interpreter search falls through to `python3`; if that can import `gi` the build proceeds, else §4.3 fails loudly with the remedy. |

## 7. Tests

Four existing monkeypatch sites reference `launcher._open_when_ready` and must go
when it does — `tests/test_port.py` (1) and `tests/test_packaging.py` (3), counted
with `grep -o _open_when_ready tests/*.py | wc -l` → `4`. Left in place they raise
`AttributeError` from `monkeypatch.setattr`, so the omission fails loudly at test
time rather than passing silently.

| Invariant | Test | Status |
|---|---|---|
| INV-4 | `tests/test_launcher_no_autoopen.py::test_server_start_opens_no_browser` | new |
| INV-5 | `tests/test_packaging.py::test_launcher_single_instance_opens_browser`, `tests/test_port.py::test_busy_port_with_explicit_port_fails_without_a_browser` | exists, must keep passing |
| INV-7 | `tests/test_packaging.py::test_launcher_falls_back_to_headless_when_tray_fails` | exists, must keep passing |

**Getting a real red run for INV-4 needs care, and the obvious fixture does not
give one.** With `_port_is_serving` stubbed to a constant `False` — what every
sibling test does — pre-fix `_open_when_ready` polls, never sees a listener, and
never calls `open_url`. The test would then pass against the unfixed code and prove
nothing. Two things are required, and only the first ships:

1. **In the shipped test**, stub `_port_is_serving` so the *first* call (the
   single-instance check in `main`) returns `False` and later calls return `True`.
   Post-fix there are no later calls, so the distinction is invisible and the test
   passes; pre-fix the poll thread sees `True` and calls `open_url`.
2. **For the one-time red run only**, the author additionally makes the fake
   `serve_forever` sleep ~0.3 s before returning, so `main()` outlives the daemon
   poll thread long enough for it to fire. Without it the race is real and the red
   is intermittent. **The shipped test carries no sleep** — post-fix there is no
   thread to race with, so it is deterministic without one.

Record the red run's output in the commit message; a test that has only ever been
green is a test nobody has seen work.

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
untouched. Two costs, both one-time and both local: rebuilding an existing `venv`
once (a full `pip install`, ~10–20 s), and the distro packages of §4.5 —
**2.5 MB installed**, measured with
`rpm -q --qf '%{SIZE}\n' <the eight packages> | awk '{s+=$1} END {print s/1048576}'`
over the Ayatana stack plus `python313-gobject`. The per-launch `pip install` stays
a no-op, measured at 0.68 s.

## 11. What checks this

| Invariant | What catches a breach |
|------|----------------------|
| INV-1 | **nothing automated** — needs the real distro packages and a real venv; manual clause in §5, and CL-0059's acceptance re-checks it |
| INV-2 | **nothing automated** — asserting an import path inside CI's own venv would pass vacuously where no system Flask exists to shadow; manual clause in §5 |
| INV-3 | **nothing automated** — manual recipe in §5; a shell-level guard has no test harness in this project |
| INV-4 | `tests/test_launcher_no_autoopen.py::test_server_start_opens_no_browser` |
| INV-5 | `tests/test_packaging.py::test_launcher_single_instance_opens_browser` + `tests/test_port.py::test_busy_port_with_explicit_port_fails_without_a_browser` |
| INV-6 | **nothing automated** — the AppImage build is not run in the test suite; the §4.3 pre-flight is itself the mechanical catcher at build time |
| INV-7 | `tests/test_packaging.py::test_launcher_falls_back_to_headless_when_tray_fails` |

Four `nothing` rows. Three are honest limits of a Python test suite over shell and
distro state; the fourth (INV-6) is converted from "silent wrong output" to "loud
failure" by §4.3, which is the best available rung short of building an AppImage in
CI on every push.

## 12. Cross-doc impact

- **README** — four claims that the browser opens automatically (the intro line, the
  "opens in your browser automatically" paragraph, the `run.sh` description, and the
  `launcher.py` file-map entry) become wrong and are corrected; §4.5's prerequisite
  table is added beside the Python-version requirement.
- **CLAUDE.md** — the *Verifying a launch by hand* bullet beginning "Intercept the
  browser-open rather than letting it spray tabs" is rewritten: on the binding path
  the interception now proves an open does **not** happen, which is the harder claim
  and exactly what that technique was written for.
- **`launcher.py` module docstring** — responsibility 4 currently reads "open the
  browser once the socket is up, and run the system-tray icon on the main thread".
  The browser clause goes.
- **`run.sh` comment** — "launcher.py owns the tray + browser-open; no separate
  xdg-open here (it would open the browser twice)" becomes wrong on its first
  clause; the double-open warning it exists to give is now moot.
- **`docs/specs/2026-07-10-standalone-launchers-design.md`** — INV-4's "the browser
  is opened only after the socket accepts a connection" sentence is superseded.
  Annotated in place, never renumbered.
- **`docs/specs/2026-07-12-system-tray-icon.md`** — §6.1 is scoped to the build
  machine only; a pointer here records that the run machine needs the same stack.
- **CHANGELOG** — `Fixed` (tray on from-source and local builds) and `Changed`
  (no automatic browser-open).
- **ROADMAP** — CL-0057 and CL-0060 flip to shipped; CL-0059 loses its blocker.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 1 | 2026-08-06 | 2 | 1 | 6 | 8 | 10 | All 25 verified, 0 unverified, all fixed. Dimensions: dim 2×6, dim 6×6, dim 4×4, dim 7×4, dim 5×2, dim 9×1, dim 10×1, dim 15×1. Two of the draft's own prescriptions were executed and found wrong: the §4.3 pre-flight checked `AyatanaAppIndicator3` only, but `pystray._appindicator` probes `AppIndicator3` first (would have failed a working host); and §4.1's rebuild guard missed a venv orphaned by a system-Python upgrade, which §6 wrongly called handled. Also corrected: an `INV-3`/`INV-6` label collision with borrowed invariants, INV-4's test contract omitting the `tray.run_tray` stub (would hang on exactly the machines this change creates), INV-4's pre-fix red run being vacuous, INV-7 claiming "no traceback" against `exc_info=True`, and a resource figure wrong by 6× (400 KB → measured 2.5 MB). |
