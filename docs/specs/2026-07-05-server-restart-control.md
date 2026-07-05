# Server restart / shutdown control (CL-0046)

**Status:** Signed off (2026-07-05) — passed `/cold-eyes` to polish-convergence
(5 loops, 2 independent cold reviewers per loop). The CRITICAL (inline-`confirm`
blocked by CSP → `data-confirm`) and HIGH (daemon thread vs the DESIGN.md §7.2
"no background threads" rule → documented carve-out) were fixed at loops 1–2 and
did not resurface; loops 3–5 surfaced only
accuracy/precision polish (all fixed), incl. grounding the restart-window in a
**measured ~150 ms cold start**. No structural/mechanical/architectural findings
remained.

**Post-sign-off correction (2026-07-05):** implementation smoke-testing (real
server on port 5099) found the signed-off restart mechanism — in-place
`os.execv` — does **not** work: Werkzeug's dev-server listening socket is not
close-on-exec, survives `execve`, and the replacement image crashes with "Address
already in use". Mechanism corrected to **spawn a fresh detached `python app.py`
via `subprocess.Popen(close_fds=True)` then `os._exit(0)`**, which the same smoke
test verified end-to-end (restart → new PID binds the port, zero errors; shutdown
→ port released). §2.1 / INV-3 updated. This is why the mechanism is verified by a
live smoke test, not just unit tests.

## 1. Problem & overview

The app is launched from a desktop icon (`contact-list.desktop` → `run.sh` →
`exec "$VENV_DIR/bin/python" app.py`). There is **no terminal attached**, so the
user has no `Ctrl-C` to stop the server and no way to restart it after pulling a
fix (like the CL-0045 sync bug). Today the only way to restart is to find and
kill the process by hand.

This change adds two controls to the **Settings** page:

- **Restart** — reload the running server with fresh code and state (the common
  case: "I updated the app, load the new code").
- **Shutdown** — stop the server cleanly. To start again the user relaunches from
  the desktop icon (the same way they start it now).

Single-user, `127.0.0.1`-only app (DESIGN.md §6.3), so the surface is one local
user; the design still applies CSRF and POST-only, consistent with every other
mutating action.

## 2. Mechanism

`app.py`'s entrypoint is `exec python app.py` with `app.run(debug=False)` — **no
reloader**, so the process does not pick up code changes on its own, and nothing
supervises/respawns it. The process must therefore act on **itself**.

### 2.1 Restart — respawn a fresh process, then exit

```python
try:
    subprocess.Popen(
        [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]],
        cwd=os.getcwd(), env=os.environ, start_new_session=True,
    )
except OSError:
    log.exception('Server restart (respawn) failed; the old process keeps serving')
    return                      # do NOT exit — leave the old server running
os._exit(0)                     # shutdown takes this path directly (no Popen)
```

Restart spawns a **fresh, detached** `python app.py` child and then exits the
current process. Rationale it works cleanly here:

- **`os.execv` in place does NOT work** — verified empirically. Werkzeug
  **deliberately** marks its listening socket inheritable
  (`werkzeug/serving.py:1105` — `srv.socket.set_inheritable(True)`, to hand the fd
  to a reloader child), overriding the PEP 446 CLOEXEC default. So the socket
  *survives* `execve`; the replacement image then fails to bind with "Address
  already in use". A smoke test on port 5099 reproduced this exactly (2× "App
  initialized", then a bind crash). So we spawn a new process instead of replacing
  the image.
- **Fresh child does not inherit the socket.** `subprocess.Popen` defaults to
  `close_fds=True`, so the child does **not** inherit the parent's (non-CLOEXEC)
  listening socket. The parent then `os._exit(0)`s, which releases the socket, and
  the child binds `127.0.0.1:PORT` cleanly. Werkzeug also sets
  `allow_reuse_address` (`SO_REUSEADDR`), covering any TIME_WAIT. The child takes
  ~150 ms to import + bind (§2.3) — far longer than the parent's immediate exit —
  so there is no live-socket bind race. (Smoke test: after-restart the port is
  held by a **new** PID, zero bind errors.)
- **Child outlives the parent.** `start_new_session=True` detaches the child into
  its own session/process group, so it keeps running after the parent exits and is
  reparented to init. `cwd`/`env` are passed explicitly so `CONTACT_LIST_PORT` and
  the working directory carry over; the **absolute** script path makes it
  CWD-independent.
- **No launcher change / no duplicate browser tab.** `run.sh` is untouched; its
  one-shot `xdg-open` ran in a separate backgrounded subshell that already
  completed, and the child runs only `python app.py`, so no second tab opens.

If the `Popen` spawn raises `OSError` the delay thread **logs** it and returns
**without** exiting — leaving the **old** server serving (a failed restart
degrades to "no restart", never to a dead server). See INV-7.

The dev server runs threaded — Flask's `app.run` defaults `threaded=True`
(`app.py:211` passes no `threaded=`; the default lives in Flask's `run`, not
Werkzeug's `run_simple`) — so any **other** in-flight request is killed when the
process exits. Accepted trade-off: the sole client is the local user who just
clicked Restart/Shutdown; there are no concurrent callers to disrupt.

**Launcher caveat.** Restart needs no supervisor because the child is
self-spawned. If the app is ever started **not** via `run.sh` (e.g. bare
`python app.py` from an odd CWD), the child still inherits `cwd=os.getcwd()` and
the absolute script path, so it launches correctly regardless.

### 2.2 Shutdown — process exit

```python
os._exit(0)
```

`os._exit` terminates immediately without running interpreter cleanup/atexit
handlers. That is intentional and safe here: SQLite writes are already committed
per-operation (no long-lived open transaction to lose), and there is no buffered
state that a clean shutdown would flush. `sys.exit()` is avoided because it only
raises `SystemExit` in the calling thread — the Werkzeug serving thread would keep
running — whereas `os._exit` stops the whole process.

### 2.3 Deferral so the HTTP response flushes first

Both actions must happen **after** the current request's response reaches the
browser, or the user sees a connection-reset instead of the confirmation page.
The route returns its response normally; the action is scheduled on a short-lived
**daemon thread** that sleeps a small fixed delay before acting:

```python
def schedule(action: str) -> None:
    if action not in ('restart', 'shutdown'):
        raise ValueError(f'unknown server action: {action}')
    threading.Thread(target=_run_after_delay, args=(action,), daemon=True).start()

def _run_after_delay(action: str) -> None:
    # Defense-in-depth: never replace/kill the process under pytest, even if a
    # test forgets to patch this out — PYTEST_CURRENT_TEST is set only during a
    # test run, never in production, so this is a no-op for the real server.
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return
    time.sleep(_FLUSH_DELAY_S)
    ...  # restart: Popen a fresh app.py (try/except OSError) then os._exit(0);
         # shutdown: os._exit(0)
```

`daemon=True` means the thread never blocks a shutdown. The delay is a **best-
effort** flush heuristic, **not** a correctness lock: `_FLUSH_DELAY_S` (0.4 s) is
generously longer than writing a sub-kilobyte response to a loopback socket, and
the request-handling thread has already returned by the time it fires. This is
acceptable because the only client is the local user who just clicked the button.
(`response.call_on_close` would give a tighter ordering signal but still cannot
run the respawn/exit inline without the same "other in-flight requests die"
trade-off, so the simple timed thread is the shortest adequate option.)

`server_control.py` defines the constant `_FLUSH_DELAY_S = 0.4` and a module
logger (`log = logging.getLogger(__name__)`, used by INV-7).

**Restart-window budget.** Time from the result page being served to the socket
being back ≈ `_FLUSH_DELAY_S` (0.4 s, during which the *old* server is still
bound and serving) + fresh-process cold start. The cold start was **measured at
~150 ms** on this venv (`python -c "import app; app.create_app()"`, 3 runs) —
comfortably inside the DESIGN.md §7.1 "Cold start" < 500 ms target, because the
heavy Google API libraries are **lazy-imported** inside `sync_contacts`, not at
startup (only Flask + Pillow + phonenumbers load on boot). So the end-to-end
window is **~0.55 s**, and the socket-unavailable gap is only the ~150 ms
cold-start part. The result page's meta-refresh (§4.2) is set to **3 s** — a >5×
margin over the measured window — so the single refresh lands well after the
socket is back, not during the gap.

## 3. Route

`POST /settings/server` in `routes/settings.py` (the Settings blueprint, `bp`),
with a single `action` form field constrained to `restart` | `shutdown`. The
module is imported as `import server_control` and called `server_control.schedule`
(no alias):

```python
@bp.route('/settings/server', methods=['POST'])
def server_control_route():
    action = request.form.get('action', '')
    if action not in ('restart', 'shutdown'):
        abort(400)
    server_control.schedule(action)
    return render_template('server_action.html', action=action)
```

The view function is named `server_control_route` so it does not shadow the
imported `server_control` module; its `url_for` endpoint is
`settings.server_control_route`.

`routes/settings.py` currently imports `Blueprint, flash, g, redirect,
render_template, request, url_for` — **not `abort`**; add `abort` to that flask
import (and `import server_control`) so the snippet runs. The route's own
`action` allow-list check makes `schedule`'s internal `ValueError` (§2.3)
unreachable from the web path — that `ValueError` is belt-and-braces for direct
callers and is exercised only by the unit test.

- **CSRF** is enforced by the existing global `_check_csrf` before_request
  (`abort(403)` on any POST without a valid token); the form includes
  `csrf_token()`. No per-route CSRF code.
- **Invalid `action`** → `400` and **no** scheduling (fail closed).
- The response is a standalone `server_action.html` page (below), not a redirect —
  the server is about to disappear, so redirecting back to a route it can no longer
  serve would just error. "Standalone" here is literal: it is a **self-contained
  HTML document with its own `<head>`**, NOT a `base.html` child (§4.2 explains
  why).

## 4. Templates

### 4.1 Settings page — new "Server" section

A `<fieldset>` appended to `settings.html`, **outside** the existing settings
`<form>` (two independent POST targets), with two single-button forms so each
action posts its own `action` value and carries its own CSRF token.

The confirmation guard uses the project's **`data-confirm` attribute** — NOT an
inline `onsubmit`/native `confirm()`. The app's CSP (`app.py` `_security_headers`)
is `default-src 'self'; style-src 'self'; …` with **no `script-src` directive at
all** (scripts fall back to `default-src 'self'`, and inline handlers are never
`'self'`), so inline event-handler attributes are blocked by the browser and would
silently never fire. The existing `static/app.js` `[data-confirm]` handler (used by
`sync.html:70` / `contact_detail.html:95`) intercepts the button **click**,
`preventDefault()`s it, shows the modal (markup already in `base.html`:
`#confirm-modal`), and on confirm calls `form.submit()`. Because programmatic
`form.submit()` does **not** include the clicked button's `name`/`value`, the
`action` value is carried in a **hidden input**, not on the button. Mirror that
exactly:

```html
<fieldset class="settings-form">
  <legend>Server</legend>
  <small class="form-hint">Restart to load updated code, or shut the server down.
     After a shutdown, relaunch from the Contact&nbsp;List icon.</small>
  <form method="post" action="{{ url_for('settings.server_control_route') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
    <input type="hidden" name="action" value="restart">
    <button type="submit" class="btn"
            data-confirm="Restart the server now? It will be briefly unavailable.">
      Restart server
    </button>
  </form>
  <form method="post" action="{{ url_for('settings.server_control_route') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
    <input type="hidden" name="action" value="shutdown">
    <button type="submit" class="btn btn-danger"
            data-confirm="Shut the server down? You will need the desktop icon to start it again.">
      Shut down server
    </button>
  </form>
</fieldset>
```

No inline JavaScript is introduced (INV-6). If JS is disabled the `data-confirm`
handler is inert and the form posts immediately — acceptable for a single-user
local tool; the action is still CSRF-gated and reversible by relaunch.

### 4.2 Result page — `server_action.html`

**Template shape.** This page does **not** extend `base.html`: `base.html`'s
`<head>` exposes only `{% block title %}` (no `{% block head %}`), and a
`<meta http-equiv="refresh">` is only honoured inside `<head>`. So
`server_action.html` is a **full standalone document** with its own
`<!DOCTYPE html>` / `<head>` (carrying the meta-refresh and a
`<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">`
for basic styling) and a minimal `<body>`. Set `data-theme` on its `<html>` from
the `settings` global (as `base.html:2` does) so a forced theme is respected;
otherwise this one transient page briefly flashes the default theme. It
deliberately forgoes the nav header — during a restart those links point at a
server that is momentarily down. (Adding a `{% block head %}` to `base.html` was the alternative; the
standalone page is chosen to keep the edit localized and avoid touching every
other page's `<head>`.)

- **Restart:** an `<h1>Restarting…</h1>` (the `Restarting` substring the route
  test asserts on) plus body copy like "The server is reloading. This page will
  reconnect automatically in a few seconds." Include
  `<meta http-equiv="refresh" content="3; url={{ url_for('contacts.contact_list') }}">`.
  This fires **once** at t=3 s — it is a one-shot navigation, not a retry loop —
  which is why 3 s comfortably clears the measured restart window (see §2.3 for
  the budget — do not re-derive it here): by the time it fires the socket is
  already back. If the restart somehow overruns 3 s the user sees a connection
  error and reloads manually; this is a rare degraded case, not the expected path.
- **Shutdown:** "Server stopped. You can close this tab; relaunch from the
  Contact List icon." **No** meta-refresh (nothing to reconnect to).

Branch on `action` in the template.

## 5. Testing

Two independent safeguards ensure **no test ever spawns-from or exits the process**:
(1) the tests below patch out the real work, and (2) `_run_after_delay` returns
early when `PYTEST_CURRENT_TEST` is set (§2.3) — so even a *missed* patch cannot
replace or kill the pytest interpreter. The tests target two different seams —
route tests patch `server_control.schedule`; the `schedule` unit test patches
`threading.Thread` — so the intro "patch it out" resolves to the specific seam per
test, below.

- **`schedule` validates action** — `schedule('bogus')` raises `ValueError`
  (asserted). For `schedule('restart')` / `schedule('shutdown')`, patch
  `threading.Thread` with a recorder and assert exactly one thread is created with
  `daemon=True`, `target=_run_after_delay`, `args=(action,)`. The recorder does
  **not** start the thread, so the real body never runs.
- **`_run_after_delay` is inert under pytest** — call it directly with
  `PYTEST_CURRENT_TEST` set (pytest sets it) and assert it returns without calling
  `subprocess.Popen` / `os._exit` (patch both to a sentinel that fails the test if
  hit). This locks the defense-in-depth guard (INV independent of the Thread patch).
- **Route: restart** — `POST /settings/server` `action=restart` with a valid CSRF
  token, `server_control.schedule` patched to a recorder → `200`, body mentions
  restarting, recorder called once with `'restart'`.
- **Route: shutdown** — same with `action=shutdown` → recorder called with
  `'shutdown'`; body mentions the icon.
- **Route: invalid action** → `400`, recorder **not** called.
- **Route: missing CSRF** → `403` (global hook), recorder **not** called.
- **Settings GET** shows both buttons (`value="restart"` / `value="shutdown"`
  present in the HTML).

## 6. Security (DESIGN.md §6)

- **Reachability.** The server binds `127.0.0.1` only (CL-0021), so the
  process-control endpoint is not reachable off-host. No new network exposure.
- **CSRF.** POST-only + the global signed-token check; a cross-origin page cannot
  forge the token, so it cannot restart/kill the server.
- **Capability framing.** This is a *local process-control* action, deliberately
  scoped to `restart` | `shutdown` (an allow-list, not an arbitrary command) — it
  respawns `python app.py` or exits, nothing user-supplied ever reaches the
  `subprocess.Popen` argv (built only from `sys.executable` + `sys.argv`). The
  `Popen` call passes a **list** (no `shell=True`), so there is no shell or
  argument-injection surface.
- **No CSP relaxation.** The confirm guard uses `data-confirm` + the existing
  `static/app.js` handler, so the strict CSP (no inline script) is untouched.
- DESIGN.md **§9 (API / Route Design)** routes table gains the
  `POST /settings/server` row. The `/settings` GET and POST rows are currently
  **absent** from that table; add them in the same edit so the settings routes
  are left fully represented, not half-listed. A one-line note in **§6.3
  (Security → General)** records the localhost + CSRF justification for exposing
  process control.

### 6.1 Reconciling DESIGN.md §7.2 ("No background threads")

DESIGN.md §7.2 states *"No background threads or task queues in v1. Sync is
user-triggered."* The one-shot delay thread (§2.3) is a **narrow, documented
exception**, not a violation of that rule's intent: the rule targets background
*application work* (polling, sync, task queues) — the daemon thread here does no
application work, exists only to let the current HTTP response flush, and the
process is gone (respawn + `os._exit`) milliseconds later. This spec's implementation
adds a one-line carve-out to §7.2 recording the exception (CL-0046), mirroring how
the Pillow C-extension exception is recorded in §3's Dependency Budget prose
(`DESIGN.md:41`). One sibling touch is needed: the two-way-sync spec's line 781
reference to §7.2 stays fine, but line 115 reads *"no background threads
(DESIGN.md §7.2 **unchanged**)"* — the word "unchanged" goes literally false once
the carve-out lands. The implementation reworks that parenthetical to
"(DESIGN.md §7.2 — sync adds no threads)" (substance is identical: sync adds no
threads). Listed in §8.

## 7. Out of scope

- No supervisor / auto-respawn (shutdown means "start again from the icon").
- No scheduled restarts, no health endpoint, no remote management.
- No change to `run.sh` or the `.desktop` launcher (the self-respawn needs neither).
- **Accepted risk (INV-7):** a *failed* respawn is logged but invisible to the
  user — the "Restarting…" page reloads onto the still-running old code, so the
  user may believe new code loaded when it did not. A user-visible failure signal
  is deliberately not built (a `Popen` failure needs a broken interpreter path,
  which the launcher makes near-impossible); revisit only if it occurs in practice.
- **Rapid double-submit** (e.g. two Restart clicks, or Restart then Shutdown)
  spawns two delay threads; the first `os._exit` wins and the second is discarded
  with the process (a double restart would spawn two children, but the first exit
  kills this process before the second thread wakes). Benign for a single local
  user; no debounce is added.

## 8. New / changed files

| File | Change | ~lines |
|------|--------|--------|
| `server_control.py` | **new** — `schedule` + `_run_after_delay` | ~30 |
| `routes/settings.py` | `POST /settings/server` view (add `abort` import) | ~10 |
| `templates/settings.html` | Server `<fieldset>` (2 button-forms) | ~15 |
| `templates/server_action.html` | **new** — restart/shutdown result page | ~20 |
| `tests/test_server_control.py` | **new** — tests §5 | ~50 |
| `DESIGN.md` | §9 routes rows (`/settings/server` + the missing `/settings` GET/POST) + §6.3 security note + §7.2 background-thread carve-out (§6.1) | ~5 |
| `docs/specs/2026-07-02-two-way-google-sync.md` | reword line 115 `§7.2 unchanged` parenthetical (§6.1) | ~1 |

## 9. Invariants

- **INV-1** Nothing user-supplied reaches the `subprocess.Popen` argv: the only
  variable is `action ∈ {restart, shutdown}` (allow-list, else `400`). The respawn
  argv is built solely from `sys.executable` + `sys.argv`, passed as a list (no
  `shell=True`). *(Testable: invalid action → 400, no schedule.)*
- **INV-2** The view returns its response **before** the action runs: the action
  is deferred to a separate daemon thread that sleeps `_FLUSH_DELAY_S`. This is a
  best-effort ordering heuristic, not a hard guarantee — the delay is not a lock
  on the socket flush. *(Testable only structurally: `schedule` spawns a
  `daemon=True` thread and returns; the exact flush ordering is not asserted.)*
- **INV-3** **On a successful restart**, a fresh child re-binds the same
  `127.0.0.1:PORT`: the `Popen` default `close_fds=True` keeps the parent's
  inheritable listening socket out of the child, and the parent's `os._exit(0)`
  releases it
  before the child (which takes ~150 ms to import + bind) gets there; `SO_REUSEADDR`
  covers any TIME_WAIT. *(Verified by the port-5099 smoke test: after-restart the
  port is held by a new PID, zero bind errors. In-place `os.execv` was tried first
  and FAILED here — the Werkzeug socket survives `execve` — hence the respawn.)*
- **INV-4** Shutdown terminates the **whole process** (`os._exit`), not just the
  calling thread.
- **INV-5** Every code path that mutates server lifecycle is CSRF-gated (POST +
  global token check) and reachable only from `127.0.0.1`.
- **INV-6** No inline JavaScript is introduced: the confirm guard is
  `data-confirm` handled by existing `static/app.js`, so the strict CSP holds.
- **INV-7** A **failed** respawn (`Popen` raises `OSError`) is caught and logged
  and the process does **not** exit; the old server keeps serving. A failed restart
  degrades to "no restart", never to a dead server. Note this degradation is
  **silent to the user**: the browser already showed "Restarting…" and its
  meta-refresh reloads onto the still-running *old* code — the failure is visible
  only in the server log. *(Not unit-tested — the guard skips execution under
  pytest, INV per code inspection.)*
- **INV-8** No test process is ever spawned-from or killed: `_run_after_delay`
  returns early when `PYTEST_CURRENT_TEST` is set. *(Testable: call it under
  pytest, assert `subprocess.Popen`/`os._exit` are not invoked.)*
