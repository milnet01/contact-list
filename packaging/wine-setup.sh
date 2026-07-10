#!/usr/bin/env bash
# One-time local setup: install a Windows Python 3.12 into the Wine prefix and the
# app deps + PyInstaller, so build-windows.sh can produce a real Windows .exe on
# Linux. This is a LOCAL PRE-FLIGHT to catch packaging errors — the shipped .exe
# is built on the native Windows CI runner (see .github/workflows/release.yml).
#
# Requires: wine (tested with wine 11.x). If the silent installer stalls, run it
# once interactively: wine packaging/.tools/python-3.12.7-amd64.exe
set -euo pipefail
cd "$(dirname "$0")/.."

PYVER="3.12.7"
INST="python-${PYVER}-amd64.exe"
TOOLS="packaging/.tools"
mkdir -p "$TOOLS"

command -v wine >/dev/null 2>&1 || { echo "wine is not installed" >&2; exit 1; }

[ -f "$TOOLS/$INST" ] || \
  curl -fL --retry 3 -m 300 "https://www.python.org/ftp/python/${PYVER}/${INST}" -o "$TOOLS/$INST"

# Silent, per-user install with python.exe on PATH inside the prefix.
wine "$TOOLS/$INST" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
wine python -m pip install --upgrade pip
wine python -m pip install -r requirements.txt pyinstaller
echo "wine python + deps ready"
