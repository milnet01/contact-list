#!/usr/bin/env bash
# Local mirror of .github/workflows/ci.yml — run this before pushing to catch
# exactly what GitHub's CI would catch.
#
# Kept in lockstep with ci.yml:
#   - the Python matrix (CI_PYTHONS below == matrix.python-version)
#   - the dev-tool pins (DEV_TOOLS below == the `pip install` in ci.yml)
#   - the three checks, in order: ruff check . , mypy , pytest
# If ci.yml changes any of these, change them here too.
#
# Differences from CI, by design:
#   - CI stops at the first failing step; this runs every check and reports all
#     failures in one pass (more useful locally). The pass/fail verdict is
#     identical — it exits non-zero iff any check under any version fails.
#   - Each matrix Python runs in its own cached venv under .ci-venvs/ (a fresh,
#     isolated env like CI), separate from the project's ./venv used to run the app.
#   - A matrix Python that isn't installed locally can't be run: it is reported as
#     a loud WARNING (with an install hint) so you know the local run does not yet
#     fully mirror CI, rather than being silently skipped.
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

# Keep in lockstep with ci.yml's matrix.python-version.
CI_PYTHONS="3.12 3.13"
# Keep in lockstep with ci.yml's dev-tool pins (ruff + mypy; not app runtime deps).
DEV_TOOLS=("ruff~=0.15.0" "mypy~=2.1")

VENV_ROOT="$APP_DIR/.ci-venvs"
failures=0
missing=""

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

for ver in $CI_PYTHONS; do
    py="python${ver}"
    if ! command -v "$py" >/dev/null 2>&1; then
        echo "!!! WARNING: $py is not installed — cannot mirror CI's Python ${ver} job."
        echo "    Install it (e.g. 'sudo zypper install python${ver//./}') to fully match CI."
        echo
        missing="$missing $ver"
        continue
    fi

    echo "########## Python ${ver} ($("$py" --version 2>&1)) ##########"
    venv="$VENV_ROOT/py${ver}"
    if [ ! -d "$venv" ]; then
        "$py" -m venv "$venv"
    fi
    "$venv/bin/python" -m pip install --quiet --upgrade pip
    "$venv/bin/pip" install --quiet -r requirements.txt
    "$venv/bin/pip" install --quiet "${DEV_TOOLS[@]}"

    run_step "[$ver] Lint (ruff)"       "$venv/bin/ruff" check .
    run_step "[$ver] Type-check (mypy)" "$venv/bin/mypy"
    run_step "[$ver] Test (pytest)"     "$venv/bin/pytest"
done

if [ "$failures" -ne 0 ]; then
    echo "CI FAILED: $failures step(s) failed — fix before pushing."
    exit 1
fi
if [ -n "$missing" ]; then
    echo "CI PASSED for installed versions, but these CI matrix Python(s) are NOT installed"
    echo "locally:$missing — the local run does not fully mirror CI until they are installed."
    exit 0
fi
echo "CI PASSED: all checks green across the full Python matrix ($CI_PYTHONS)."
