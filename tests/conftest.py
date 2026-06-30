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
