"""Self-restart / shutdown for the local dev server (CL-0046).

The app is launched from a desktop icon (``run.sh`` → ``exec python launcher.py``,
``debug=False`` so no reloader) with no terminal attached, so the user has no
Ctrl-C. These helpers let the Settings page restart the process (reload code
after an update) or stop it. Both are deferred onto a short-lived daemon thread
so the HTTP response reaches the browser first (spec
``docs/specs/2026-07-05-server-restart-control.md``).

DESIGN.md §7.2 forbids background threads for *application work*; this one-shot
delay thread does no application work and the process is gone milliseconds later,
so it is a documented, narrow exception (§7.2 carve-out).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

log = logging.getLogger(__name__)

# Set in a restart child's environment; launcher.py waits for the parent to
# release the port when it sees it (CL-0054, spec §2.1.2).
RESTART_MARKER = 'CONTACT_LIST_RESTARTING'

# Long enough for a sub-kilobyte response to flush to a loopback socket before we
# replace/exit the process; short enough to feel instant. Best-effort, not a lock.
_FLUSH_DELAY_S = 0.4


def schedule(action: str) -> None:
    """Schedule a ``'restart'`` or ``'shutdown'`` shortly after the current
    response is sent. Raises ``ValueError`` on any other action."""
    if action not in ('restart', 'shutdown'):
        raise ValueError(f'unknown server action: {action}')
    threading.Thread(target=_run_after_delay, args=(action,), daemon=True).start()


def _is_within(path: str, directory: str) -> bool:
    try:
        real_dir = os.path.realpath(directory)
        return os.path.commonpath([os.path.realpath(path), real_dir]) == real_dir
    except ValueError:  # different drives on Windows
        return False


def _respawn_command() -> tuple[list[str], dict[str, str]]:
    """The argv and environment for a restart child (CL-0063, spec §2.1.1).

    Frozen, ``sys.executable`` is the program itself, so it is not passed its own
    path again; inside an AppImage it also lives on a mount that vanishes when
    this process exits, so the AppImage file (``$APPIMAGE``) is re-run instead.
    The ``APPDIR`` test matters because ``APPIMAGE`` is inherited by anything an
    AppImage starts. A frozen child also gets the bundle off ``LD_LIBRARY_PATH``
    and PyInstaller's inherited state reset, or it would load from the old bundle.
    """
    if not getattr(sys, 'frozen', False):
        argv = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
        env = dict(os.environ)
    else:
        from browser import _system_env

        env = _system_env()
        env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        appimage = os.environ.get('APPIMAGE')
        appdir = os.environ.get('APPDIR')
        if appimage and appdir and _is_within(sys.executable, appdir):
            argv = [appimage, *sys.argv[1:]]
        else:
            argv = [sys.executable, *sys.argv[1:]]
    env[RESTART_MARKER] = '1'
    return argv, env


def _run_after_delay(action: str) -> None:
    """Wait for the response to flush, then restart or shut down.

    Restart spawns a **fresh, detached** copy of the current program (the
    command ``_respawn_command`` builds) and then exits this one. We deliberately do NOT
    ``os.execv`` in place: Werkzeug's dev-server
    listening socket is not close-on-exec, so it survives ``execve`` and the
    replacement image fails to re-bind the port ("Address already in use").
    ``subprocess.Popen`` defaults to ``close_fds=True``, so the child does NOT
    inherit that socket and binds cleanly once the parent exits (which releases
    it); ``start_new_session=True`` keeps the child alive after we go.

    Shutdown exits the whole process with ``os._exit`` (not ``sys.exit``, which
    would only unwind the calling thread and leave the serving thread alive).
    """
    # Defense-in-depth: never spawn/kill the process under pytest, even if a test
    # forgets to patch this out. PYTEST_CURRENT_TEST is set only during a test
    # run, never in production, so this is a no-op for the real server.
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return
    time.sleep(_FLUSH_DELAY_S)
    if action == 'restart':
        try:
            argv, env = _respawn_command()
            subprocess.Popen(
                argv, cwd=os.getcwd(), env=env, start_new_session=True,
            )
        except OSError:
            # Spawn failed: leave the old server serving rather than exit into
            # nothing — a failed restart degrades to "no restart", never a dead
            # server.
            log.exception('Server restart (respawn) failed; the old process keeps serving')
            return
    os._exit(0)
