#!/usr/bin/env bash
# Launch the Contact List app
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/venv"

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Sync dependencies on EVERY launch so a pulled update (e.g. the new pystray dep
# for the tray icon) installs even into an existing venv. Idempotent; a small
# fixed cost (~1-3s) once satisfied.
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# Run the app. launcher.py owns the tray + browser-open; no separate xdg-open here
# (it would open the browser twice).
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" launcher.py
