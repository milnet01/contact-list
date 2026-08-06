"""Entry point for Contact List — used by the frozen (PyInstaller) apps AND the
from-source `./run.sh` (both route through here).

Responsibilities, in order:
 1. If invoked with --google-auth (frozen only), run the OAuth flow and exit.
 2. If the app is already serving on the port, just open the browser and exit.
 3. When frozen, create the config dir and install a file log (no console).
 4. Build the app, start the web server on a background thread, and run the
    system-tray icon on the main thread. A normal start opens NO browser (CL-0060) —
    the tray icon's "Open Contact List" is the way in. Where the tray cannot start
    at all, the server still runs headless and the browser is opened as a fallback,
    because otherwise nothing would be able to reach it.

app.py is unchanged; `python app.py` from source stays a headless server (no tray).
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import socket
import sys
import threading

from browser import open_url


def _port_is_serving(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _install_file_logging() -> None:
    """Frozen-only: ensure the 0700 config dir exists, then log to a file there.
    Runs before create_app(), so it also guarantees the dir for the frozen DB.
    Sets the root level/formatter itself (app.py's basicConfig is a no-op once a
    handler exists)."""
    from config import _CONFIG_DIR, ensure_private_dir
    ensure_private_dir(_CONFIG_DIR)
    # Rotating so a long-lived desktop install's log (Werkzeug logs every request
    # at INFO) can't grow without bound: 1 MB x 3 files.
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(_CONFIG_DIR, 'contact-list.log'),
        maxBytes=1_000_000, backupCount=3,
    )
    handler.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _emit(msg: str, *, err: bool = False) -> None:
    """Write one line to the console, if there is one.

    A frozen windowed build (packaging/contact-list.spec sets console=False) can
    have sys.stdout/sys.stderr as None, where a bare print() raises. Deliberately
    a print and not a log: on the frozen path _install_file_logging() sends
    logging to a file, which is nowhere a process manager reads — and at
    port-resolution time it has not even run yet.
    """
    stream = sys.stderr if err else sys.stdout
    if stream is not None:
        print(msg, file=stream, flush=True)


def main() -> int:
    if getattr(sys, 'frozen', False) and '--google-auth' in sys.argv:
        from google_auth import main as auth_main
        return auth_main()

    from config import Config, PortError, resolve_port
    try:
        port, port_explicit = resolve_port(Config.PORT)
    except PortError as exc:
        _emit(f'error: {exc}', err=True)
        return 2

    if _port_is_serving('127.0.0.1', port):
        if port_explicit:
            # PORT named this port and something else already holds it. The
            # caller asked for a specific port and did not get it — that is a
            # failure, not a hand-off, so no browser and a non-zero exit
            # (spec INV-4). The INV-4 hand-off below is for a hand launch only.
            _emit(
                f'error: PORT={port} is already in use by another process',
                err=True,
            )
            return 1
        open_url(f'http://127.0.0.1:{port}')
        return 0

    if getattr(sys, 'frozen', False):
        _install_file_logging()

    # On Linux, pin pystray to the appindicator backend (SNI over DBus) BEFORE
    # tray.py imports pystray (spec §4.2). setdefault honours an explicit user
    # PYSTRAY_BACKEND override.
    os.environ.setdefault('PYSTRAY_BACKEND', 'appindicator')

    from app import create_app
    from werkzeug.serving import make_server
    try:
        app = create_app()
        # The tray must own the main thread, so the server moves to a dedicated
        # non-daemon thread via a stoppable handle. threaded=True preserves
        # app.run()'s default concurrency (make_server defaults threaded=False;
        # spec §5). The constructor binds the socket, so a bind failure (port in
        # use) is caught here and returns 1, like create_app().
        server = make_server('127.0.0.1', port, app, threaded=True)
    except Exception:
        logging.exception('Server startup failed')
        return 1

    # make_server prints no banner (unlike app.run), so this is the only URL line
    # on the path a process manager runs.
    _emit(f'Listening on http://127.0.0.1:{port}')

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()

    if os.environ.get('LWSM_MANAGED') == '1':
        # Presentation hint only: a managed run shows no tray icon and serves
        # headless, logging as normal (CL-0056). Taken BEFORE the try so the
        # fallback below keeps logging the truth — nothing here failed. Nothing
        # else is conditioned on this variable: it is unauthenticated and
        # trivially forged, so it may change only whether an icon appears.
        # No quit path without a tray is correct — a managed server must be
        # stoppable only by its manager.
        server_thread.join()
        return 0

    try:
        import tray
        tray.run_tray(server, port)  # blocks on the main thread until Quit
    except Exception:
        # Graceful fallback: no tray → still serve. INFO, not a warning: nobody is
        # worse off (2026-07-12-system-tray-icon.md INV-3).
        logging.info(
            'system tray unavailable or failed; running without an icon', exc_info=True
        )
        # No icon means no way in, so open the page after all rather than leave a
        # running server the user cannot reach — on a frozen windowed build the
        # "Listening on" line above may go nowhere (stdout is None). This is the ONLY
        # start-path open that survives CL-0060, and it is deliberately inside the
        # except: a working tray opens nothing. make_server already bound the socket,
        # so no readiness poll is needed. A managed run returned above and never
        # reaches here.
        open_url(f'http://127.0.0.1:{port}')
        # Join the server thread so we live as long as the server does.
        server_thread.join()
        return 0

    # Quit path: run_tray returned because on_quit called server.shutdown(); reap
    # the now-finished server thread so the port is released (INV-1).
    server_thread.join()
    return 0


if __name__ == '__main__':
    sys.exit(main())
