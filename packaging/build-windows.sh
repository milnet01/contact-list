#!/usr/bin/env bash
# Build Contact-List.exe under Wine (LOCAL PRE-FLIGHT — the shipped .exe is built
# on the native Windows CI runner). Icons are generated natively (Pillow on the
# Linux side) so only PyInstaller runs under Wine. Run packaging/wine-setup.sh once
# first to install the Windows Python + deps into the Wine prefix.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v wine >/dev/null 2>&1 || { echo "wine is not installed" >&2; exit 1; }

bash packaging/make-icons.sh                       # native: produces packaging/icon.ico
wine python -m PyInstaller --noconfirm packaging/contact-list.spec

ls -la dist/Contact-List.exe
echo "built: dist/Contact-List.exe (onefile, under Wine)"
