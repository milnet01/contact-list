"""Resolve bundled read-only resources in both source and frozen (PyInstaller)
runs. Frozen apps unpack data under ``sys._MEIPASS``; from source the base is this
file's directory (the repo root)."""
from __future__ import annotations

import os
import sys


def resource_path(*parts: str) -> str:
    """Absolute path to a bundled resource (templates/static/migrations)."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)
