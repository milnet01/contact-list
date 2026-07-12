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
from __future__ import annotations

import logging
import logging.handlers
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


if __name__ == '__main__':
    sys.exit(main())
