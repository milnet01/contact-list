"""System-tray icon with Open / Restart / Quit (CL-0052).

Cross-platform via pystray. On Linux the appindicator backend (SNI over DBus)
is forced by launcher.py before this module is imported — see
docs/specs/2026-07-12-system-tray-icon.md §4.2. The tray owns the MAIN thread;
the web server runs on a background thread whose stoppable handle is passed in.
Any tray-init failure raises so launcher.py can fall back to headless (INV-3).
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

import server_control
from browser import open_url
from resources import resource_path

if TYPE_CHECKING:
    import pystray
    from PIL.Image import Image


class _ServerHandle(Protocol):
    """The stoppable Werkzeug server handle the tray needs (launcher.py passes it)."""
    def shutdown(self) -> None: ...


def _load_icon_image() -> Image:
    """Load the committed master icon (packaging/icon.png) via Pillow and let it
    downscale in memory. NOT the git-ignored generated contact-list.png, which is
    absent on a fresh from-source clone (spec §6.2)."""
    from PIL import Image
    return Image.open(resource_path('packaging', 'icon.png'))


def _open(port: int) -> None:
    open_url(f'http://127.0.0.1:{port}')


def _restart() -> None:
    # Reuse the CL-0046 respawn; on the tray path the 0.4s flush delay is a no-op.
    server_control.schedule('restart')


def _quit(icon: pystray.Icon, server: _ServerHandle) -> None:
    server.shutdown()  # unblocks serve_forever() on the server thread
    icon.stop()        # makes run_tray's Icon.run() return on the main thread


class TrayStopper:
    """Lets another thread take the tray down when the server stops (CL-0108).

    The server can stop before the icon's loop is up, so a stop that arrives
    first is remembered and applied when the icon comes up. Icon.stop() is safe
    off the main thread: the GTK backend queues it on its loop, Win32 posts a
    message. That is why launcher.py calls stop() from the server thread and
    never from a signal handler.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._icon: pystray.Icon | None = None
        self._stopped = False

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            icon = self._icon
        if icon is not None:
            icon.stop()

    def _attach(self, icon: pystray.Icon) -> None:
        with self._lock:
            self._icon = icon
            stopped = self._stopped
        if stopped:
            icon.stop()


def _on_ready(icon: pystray.Icon, stopper: TrayStopper) -> None:
    """pystray's setup callback: runs once the loop is up, when stop() works."""
    icon.visible = True  # a custom setup must show the icon itself
    stopper._attach(icon)


def run_tray(server: _ServerHandle, port: int, stopper: TrayStopper) -> None:
    """Build the icon and run the pystray event loop ON THE CALLING (main)
    thread — blocks until Quit or stopper.stop(). Raises on any tray-init
    failure so the caller can fall back to headless."""
    import pystray  # lazy: backend is chosen at import time, after launcher sets PYSTRAY_BACKEND

    menu = pystray.Menu(
        pystray.MenuItem('Open Contact List', lambda icon, item: _open(port)),
        pystray.MenuItem('Restart', lambda icon, item: _restart()),
        pystray.MenuItem('Quit', lambda icon, item: _quit(icon, server)),
    )
    icon = pystray.Icon('contact-list', _load_icon_image(), 'Contact List', menu)
    icon.run(setup=lambda icon: _on_ready(icon, stopper))
