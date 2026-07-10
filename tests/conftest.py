"""Top-level pytest configuration."""

from __future__ import annotations

# Force Qt's offscreen QPA platform before anything imports QApplication.
# Contact_List doesn't ship a Qt UI today, but adding the safe default
# here makes it impossible for a future Qt-using test (or a transitive
# import that touches Qt) to flash a real window onto the desktop
# hosting the test runner. `setdefault` lets a CI override
# (e.g. QT_QPA_PLATFORM=minimal) still win.
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Isolation: config.py persists a secret key into ~/.config/contact-list on its
# first import when SECRET_KEY is unset. conftest loads before any test module
# imports config/app, so setting a throwaway key here keeps the whole suite from
# writing into the real user config dir — order-independent, unlike a guard in a
# single test module. setdefault lets a real CI SECRET_KEY still win.
os.environ.setdefault("SECRET_KEY", "test-key-not-persisted")
