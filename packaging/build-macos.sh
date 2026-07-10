#!/usr/bin/env bash
# macOS ONLY (runs on the macos-latest CI runner — cannot be built or legally
# virtualised on Linux). Build the .app, ad-hoc code-sign it (required for the
# binary to run at all on Apple Silicon), and wrap it in a .dmg with an
# Applications shortcut so the user can drag-to-install.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

bash packaging/make-icons.sh                        # produces packaging/icon.icns on Darwin
"$PY" -m PyInstaller --noconfirm packaging/contact-list.spec

APP="dist/Contact List.app"
# Ad-hoc signature (NOT notarization). Apple Silicon refuses to execute unsigned
# Mach-O code; ad-hoc suffices to run. PyInstaller ad-hoc-signs the raw binary
# during the build; re-sign after the .app is assembled so the bundle stays valid.
codesign --force --sign - "$APP"

# Stage a DMG source folder with the .app plus an /Applications symlink to drag onto.
STAGE="build/dmg"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "Contact List" -srcfolder "$STAGE" -format UDZO -ov Contact-List.dmg
echo "built: Contact-List.dmg"
