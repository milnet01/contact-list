#!/usr/bin/env bash
# Derive per-OS icon formats from packaging/icon.png. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
# Resolve an interpreter across Linux (venv), CI (python3), Windows Git-Bash (python).
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in ./venv/bin/python python3 python; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi

"$PY" - <<'PY'
from PIL import Image
m = Image.open('packaging/icon.png')
# Windows multi-size .ico
m.save('packaging/icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
# Linux AppImage 256px
m.resize((256, 256), Image.LANCZOS).save('packaging/contact-list.png')
PY

# macOS .icns (Darwin only; iconutil is macOS-only)
if [ "$(uname)" = "Darwin" ]; then
  ICONSET="packaging/icon.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    "$PY" -c "from PIL import Image; Image.open('packaging/icon.png').resize(($s,$s), Image.LANCZOS).save('$ICONSET/icon_${s}x${s}.png')"
    d=$((s * 2))
    "$PY" -c "from PIL import Image; Image.open('packaging/icon.png').resize(($d,$d), Image.LANCZOS).save('$ICONSET/icon_${s}x${s}@2x.png')"
  done
  iconutil -c icns "$ICONSET" -o packaging/icon.icns
  rm -rf "$ICONSET"
fi
echo "icons generated"
