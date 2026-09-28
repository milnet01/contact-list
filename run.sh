#!/usr/bin/env bash
# Launch the Contact List app
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/venv"

# The tray icon's appindicator backend imports `gi` (PyGObject), a distro package
# with no binary wheel — so the venv must be able to see the system one (CL-0057).
# Two ways an existing venv can be unusable, and neither is "the directory is
# missing": include-system-site-packages is fixed at creation, so a venv predating
# this change can never gain it; and a venv whose base interpreter was removed by a
# distro Python upgrade still looks present while being unable to run at all.
if [ -d "$VENV_DIR" ] && {
       ! grep -q '^include-system-site-packages = true' "$VENV_DIR/pyvenv.cfg" 2>/dev/null ||
       ! "$VENV_DIR/bin/python" -c '' 2>/dev/null
   }; then
    echo "Rebuilding venv so the tray icon can find the system GTK libraries..."
    rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
    # --system-site-packages makes pip treat distro packages as already installed,
    # so a plain install would leave the app running on the distro's Flask/Pillow
    # instead of our pinned ones. --ignore-installed forces OURS into the venv;
    # `gi` isn't in requirements.txt so it stays borrowed from the system. One-time
    # cost — the per-launch sync below stays a no-op.
    "$VENV_DIR/bin/pip" install --quiet --ignore-installed -r "$APP_DIR/requirements.txt"
fi

# Sync dependencies on EVERY launch so a pulled update (e.g. the new pystray dep
# for the tray icon) installs even into an existing venv. Idempotent; a small
# fixed cost (~1-3s) once satisfied.
#
# A requirement with no copy inside the venv is installed with --ignore-installed,
# as at creation above: otherwise pip counts the distro's copy as installed and a
# dependency added later runs on the distro's version (CL-0078). One with a venv
# copy needs no flag -- the venv's site-packages comes first, so pip upgrades it.
#
# Failure here is a warning, not a stop: the venv already holds what the app
# needed yesterday, so being offline must not stop it starting (CL-0078).
sync_ok=1
local_pkgs=$("$VENV_DIR/bin/pip" list --local --format=freeze 2>/dev/null \
             | cut -d= -f1 | tr 'A-Z_.' 'a-z--') || sync_ok=0
missing=()
while IFS= read -r req; do
    name=$(printf '%s' "$req" | sed -E 's/[[:space:]<>=~!;[].*//' | tr 'A-Z_.' 'a-z--')
    grep -qx -- "$name" <<<"$local_pkgs" || missing+=("$req")
done < <(grep -Ev '^[[:space:]]*(#|$)' "$APP_DIR/requirements.txt")
if [ "${#missing[@]}" -gt 0 ]; then
    "$VENV_DIR/bin/pip" install --quiet --ignore-installed "${missing[@]}" || sync_ok=0
fi
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt" || sync_ok=0
if [ "$sync_ok" -eq 0 ]; then
    echo "warning: could not update dependencies (offline?) -- starting with the ones already installed." >&2
fi

# Run the app. launcher.py owns the tray, and owns the only two browser-opens left:
# the single-instance hand-off, and the fallback when the tray fails to appear
# (CL-0060). A normal launch opens nothing, so don't add an xdg-open here.
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" launcher.py
