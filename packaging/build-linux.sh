#!/usr/bin/env bash
# Build the Linux AppImage. Local pre-flight AND the exact steps CI runs.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in ./venv/bin/python python3 python; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi

# PyInstaller can only bundle what the BUILD interpreter can import. Without this
# check the build "succeeds" while logging "Hidden import 'gi.repository.DBus' not
# found" and ships an AppImage with no tray icon (CL-0057). Runs before the ~100 MB
# of tool downloads below so a doomed build fails in a second, not a minute.
# The probe mirrors every require_version() pystray actually makes: Gtk 3.0 and
# Gio 2.0 / DBus 1.0 (via pystray/_util/notify_dbus.py — DBus is the one commit
# 3c817fc already had to fix), then AppIndicator3 with AyatanaAppIndicator3 as the
# fallback, in that order. Checking only Ayatana would reject a host carrying the
# older typelib, on which the tray works fine.
if [ -z "$PY" ]; then
  echo "error: no Python interpreter found (tried \$PYTHON, ./venv/bin/python, python3, python)." >&2
  exit 1
fi
# Capture stderr rather than discarding it: the interpreter's last line is what
# NAMES the missing namespace ("ValueError: Namespace DBus not available").
if ! gi_err=$("$PY" -c "import gi
for ns, ver in (('Gtk','3.0'), ('Gio','2.0'), ('DBus','1.0')): gi.require_version(ns, ver)
try: gi.require_version('AppIndicator3','0.1')
except ValueError: gi.require_version('AyatanaAppIndicator3','0.1')" 2>&1); then
  echo "error: $PY cannot load the GI typelibs pystray needs — the AppImage would have no tray icon." >&2
  echo "       ${gi_err##*$'\n'}" >&2
  echo "       Install the GI stack (see README), or point \$PYTHON at an interpreter that has it." >&2
  exit 1
fi

TOOLS="packaging/.tools"
APPIMAGETOOL="$TOOLS/appimagetool-x86_64.AppImage"
# Pin a specific release + checksum so a moved/altered download fails loudly.
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1"

# The AppImage "runtime" (the small ELF that makes the output self-mounting).
# We fetch it OURSELVES with curl and pass it via --runtime-file below, because
# appimagetool's built-in downloader hangs indefinitely on some networks (it
# leaves the connection in CLOSE-WAIT and never times out). curl follows redirects
# and honours timeouts, so it's reliable. NOTE: "continuous" is a rolling tag — if
# upstream rebuilds it, this checksum stops matching and the build fails loudly;
# re-run `sha256sum packaging/.tools/runtime-x86_64` and update the hash here.
RUNTIME="$TOOLS/runtime-x86_64"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"
RUNTIME_SHA256="1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf"

mkdir -p "$TOOLS"

# Download to <dest> if missing, then verify the sha256 on EVERY run (so a
# truncated/partial cached file from a killed prior run is caught, not reused).
fetch_verify() {  # fetch_verify <url> <dest> <sha256>
  local url="$1" dest="$2" sha="$3"
  [ -f "$dest" ] || curl -fL --retry 3 -m 120 "$url" -o "$dest"
  echo "${sha}  ${dest}" | sha256sum -c -
}

fetch_verify "$APPIMAGETOOL_URL" "$APPIMAGETOOL" "$APPIMAGETOOL_SHA256"
chmod +x "$APPIMAGETOOL"
fetch_verify "$RUNTIME_URL" "$RUNTIME" "$RUNTIME_SHA256"

bash packaging/make-icons.sh
"$PY" -m PyInstaller --noconfirm packaging/contact-list.spec

APPDIR="build/AppDir"
rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/bin"
cp -r dist/Contact-List/* "$APPDIR/usr/bin/"
cp packaging/contact-list.png "$APPDIR/contact-list.png"

cat > "$APPDIR/contact-list.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Contact List
Exec=Contact-List
Icon=contact-list
Categories=Office;
DESK

cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Contact-List" "$@"
RUN
chmod +x "$APPDIR/AppRun"

# --runtime-file uses our pre-fetched runtime so appimagetool never does its own
# (hang-prone) download. --appimage-extract-and-run avoids needing FUSE to *run*
# appimagetool itself on the build host.
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run \
  --runtime-file "$RUNTIME" "$APPDIR" Contact-List-x86_64.AppImage
echo "built: Contact-List-x86_64.AppImage"
