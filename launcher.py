"""Frozen (PyInstaller) entrypoint for Contact List.

Responsibilities, in order:
 1. If invoked with --google-auth (frozen only), run the OAuth flow and exit.
 2. If the app is already serving on the port, just open the browser and exit.
 3. When frozen, create the config dir and install a file log (no console).
 4. Build the app, open the browser once the socket is up, run the server.

app.py is unchanged; `python app.py` from source still works as before.
"""
from __future__ import annotations

import logging
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
    handler = logging.FileHandler(os.path.join(_CONFIG_DIR, 'contact-list.log'))
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

    from app import create_app
    try:
        app = create_app()
        threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
        app.run(host='127.0.0.1', port=port, debug=False)
    except Exception:
        logging.exception('Server startup failed')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
