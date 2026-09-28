# shellcheck shell=bash
# Sourced by the packaging scripts (CL-0078) -- not run on its own.
# Sets PY to an interpreter: $PYTHON if set, else the first of ./venv/bin/python,
# python3, python (Linux venv, CI, Windows Git-Bash). Exits when none is found:
# an empty PY would otherwise run the next line's heredoc as a command named "-".
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in ./venv/bin/python python3 python; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi
if [ -z "$PY" ]; then
  echo "error: no Python interpreter found (tried \$PYTHON, ./venv/bin/python, python3, python)." >&2
  exit 1
fi
