#!/usr/bin/env bash
# Launch the Contact List app
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/venv"

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
fi

# Open browser after a short delay
(sleep 1 && xdg-open "http://localhost:5002" 2>/dev/null) &

# Run the app
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" app.py
