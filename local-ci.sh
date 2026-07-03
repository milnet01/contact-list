#!/usr/bin/env bash
# Local mirror of .github/workflows/ci.yml — run this before pushing to catch
# exactly what GitHub's CI would catch. Keep the three checks below (and the
# pinned dev-tool versions) in lockstep with ci.yml; if one changes, change both.
#
# Difference from CI, by design: GitHub stops at the first failing step, whereas
# this runs all three and reports every failure in one pass (more useful locally).
# The pass/fail verdict is identical — this exits green iff all three are green.
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/venv"
cd "$APP_DIR"

# Match CI's environment: app deps from requirements.txt, plus ruff/mypy pinned
# to the same specifiers as ci.yml (they are dev tools, not runtime deps).
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r requirements.txt
"$VENV_DIR/bin/pip" install --quiet 'ruff~=0.15.0' 'mypy~=2.1'

failures=0
run_step() {  # run_step "<label>" <command...>
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

run_step "Lint (ruff)"       "$VENV_DIR/bin/ruff" check .
run_step "Type-check (mypy)" "$VENV_DIR/bin/mypy"
run_step "Test (pytest)"     "$VENV_DIR/bin/pytest"

if [ "$failures" -ne 0 ]; then
    echo "CI FAILED: $failures step(s) failed — fix before pushing."
    exit 1
fi
echo "CI PASSED: all checks green."
