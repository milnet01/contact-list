"""Open the user's web browser, safely from a frozen (PyInstaller) build.

A frozen build runs with the PyInstaller bundle dir on LD_LIBRARY_PATH so the app
finds its own bundled libraries. But opening the browser shells out to a SYSTEM
program (xdg-open -> /bin/sh), which must NOT inherit that path or it loads our
bundled libs (e.g. an Ubuntu-built libreadline) and dies with a symbol-lookup
error on a host with a different libreadline. So on a frozen Linux build we spawn
the opener with the pre-bundle environment restored. PyInstaller saves the
original value in LD_LIBRARY_PATH_ORIG.
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser


def _system_env() -> dict[str, str]:
    """A copy of the environment with the PyInstaller bundle removed from the
    dynamic-linker path, so a spawned SYSTEM program loads the host's libraries."""
    env = dict(os.environ)
    orig = env.pop('LD_LIBRARY_PATH_ORIG', None)
    if orig is None:
        env.pop('LD_LIBRARY_PATH', None)
    else:
        env['LD_LIBRARY_PATH'] = orig
    return env


def open_url(url: str) -> None:
    """Open ``url`` in the user's browser. On a frozen Linux build, spawn xdg-open
    with the host's library path (see module docstring); everywhere else use the
    stdlib webbrowser, which has no such leak."""
    if getattr(sys, 'frozen', False) and sys.platform.startswith('linux'):
        try:
            subprocess.Popen(
                ['xdg-open', url], env=_system_env(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            pass  # xdg-open missing: fall through to webbrowser as a last resort
    webbrowser.open(url)
