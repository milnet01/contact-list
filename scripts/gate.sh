#!/usr/bin/env bash
# The one list of CI checks (local-gate.md § 3). ci.yml runs it on each GitHub
# runner and local-ci.sh runs it once per matrix Python, so the local run and
# GitHub cannot disagree about which steps exist. Tools are taken from PATH.
#
#   scripts/gate.sh python   ruff, mypy, djlint and pytest in the active environment
#   scripts/gate.sh js       ESLint on the browser script (after `npm ci`)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

failures=0
step() {  # step "<label>" <command...>
    local label="$1"; shift
    echo "=== $label ==="
    if "$@"; then
        echo "--- $label: PASS"
    else
        echo "--- $label: FAIL"
        failures=$((failures + 1))
    fi
    echo
}

case "${1:-}" in
    python)
        step "Lint (ruff)" ruff check .
        step "Type-check (mypy)" mypy
        step "Lint templates (djlint)" djlint templates --lint
        step "Test (pytest)" pytest
        ;;
    js)
        step "Lint JavaScript (eslint)" npx --no-install eslint static/
        ;;
    *)
        echo "usage: $0 python|js" >&2
        exit 2
        ;;
esac
[ "$failures" -eq 0 ]
