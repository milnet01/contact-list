#!/usr/bin/env bash
# Run GitHub's CI locally, before pushing. The checks are scripts/gate.sh and the
# dev-tool pins are requirements-dev.txt; ci.yml uses the same two files, so
# there is one list of steps (local-gate.md § 3). This script adds the matrix
# loop, and fails if its Python list differs from ci.yml's.
#
# By design:
#   - Each matrix Python runs in its own cached venv under .ci-venvs/ (a fresh,
#     isolated env like CI), separate from the project's ./venv used to run the app.
#
# Getting the matrix interpreters: a distro usually ships exactly one Python, so
# most of the matrix would otherwise be unrunnable here. `uv` fetches any CPython
# without root, which is what lets this script cover the whole matrix rather than
# just the system version. It is resolved in this order:
#   1. python<ver> on PATH (a distro or pyenv install)
#   2. `uv python find <ver>`  — already fetched
#   3. `uv python install <ver>` — fetch it now, once, then reuse
# If a version cannot be obtained at all, the run FAILS rather than passing with a
# warning: a green light that silently skipped a third of the matrix is worse than
# no green light, and that is exactly what shipped the 3.12/3.14 gap.
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" || exit 1

# The checks themselves are scripts/gate.sh, which ci.yml runs too; the dev-tool
# pins are requirements-dev.txt, which both install. What this script owns is
# the matrix loop, so it checks its list against ci.yml's below.
CI_PYTHONS="3.12 3.13 3.14"

VENV_ROOT="$APP_DIR/.ci-venvs"
failures=0
unobtainable=""

# The legs must be ci.yml's legs (local-gate.md § 3): a Python added there and
# not here would never run locally, and nothing else would say so.
wf_pythons=$(grep -oE 'python-version: \[[^]]*\]' .github/workflows/ci.yml | grep -oE '[0-9]+\.[0-9]+' | tr '\n' ' ')
if [ "${wf_pythons% }" != "$CI_PYTHONS" ]; then
    echo "!!! ERROR: CI_PYTHONS ($CI_PYTHONS) != ci.yml's matrix (${wf_pythons% }). Make them agree."
    exit 1
fi

# uv installs to ~/.local/bin, which isn't always on a non-login shell's PATH.
export PATH="$HOME/.local/bin:$PATH"

resolve_python() {  # resolve_python <version> -> prints an interpreter path, or nothing
    local ver="$1" p
    if command -v "python${ver}" >/dev/null 2>&1; then
        command -v "python${ver}"; return 0
    fi
    command -v uv >/dev/null 2>&1 || return 1
    if p=$(uv python find "$ver" 2>/dev/null) && [ -x "$p" ]; then
        echo "$p"; return 0
    fi
    # Not present yet — fetch it once (a ~35 MB download), then re-resolve.
    echo "    fetching CPython ${ver} via uv (one-time)..." >&2
    uv python install "$ver" >&2 2>/dev/null || return 1
    p=$(uv python find "$ver" 2>/dev/null) && [ -x "$p" ] && { echo "$p"; return 0; }
    return 1
}

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
    if ! py=$(resolve_python "$ver"); then
        echo "!!! ERROR: cannot obtain Python ${ver} — CI's ${ver} job is NOT mirrored."
        echo "    Install uv (https://docs.astral.sh/uv/) so this script can fetch it,"
        echo "    or install python${ver} yourself."
        echo
        unobtainable="$unobtainable $ver"
        continue
    fi

    echo "########## Python ${ver} ($("$py" --version 2>&1)) ##########"
    venv="$VENV_ROOT/py${ver}"

    # CI builds a FRESH environment every run; reusing a venv here would drift
    # from that. Most importantly, a dependency REMOVED from requirements.txt
    # lingers in an existing venv — so the code still imports it locally and
    # fails in CI. Stamp the venv with what produced it and rebuild when that
    # changes, which keeps the common case fast without the stale-env class of
    # false pass.
    stamp="$venv/.ci-stamp"
    want="$("$py" -c 'import sys;print(sys.version)' 2>&1)|$(sha256sum requirements.txt requirements-dev.txt | cut -d' ' -f1 | tr '\n' ' ')"
    if [ -d "$venv" ] && [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
        echo "    inputs changed since this venv was built — rebuilding it"
        rm -rf "$venv"
    fi
    if [ ! -d "$venv" ]; then
        "$py" -m venv "$venv"
    fi
    # --upgrade on both, because requirements.txt pins MAJORS only and CI builds
    # a fresh environment every run -- so CI resolves to the newest in-range
    # release while a plain `pip install -r` into a cached venv reports
    # "already satisfied" and keeps the old one. The stamp below cannot catch
    # that: it hashes our inputs, and none of them changes when UPSTREAM
    # publishes flask 3.2.0 or ruff 0.16.5. Without this the cached venv drifts
    # behind CI silently, which is the stale-env false pass this venv-stamping
    # was written to close, and it hides the dependency drift DESIGN.md §3
    # requires be surfaced.
    if ! "$venv/bin/python" -m pip install --quiet --upgrade pip \
       || ! "$venv/bin/pip" install --quiet --upgrade -r requirements.txt \
       || ! "$venv/bin/pip" install --quiet --upgrade -r requirements-dev.txt; then
        # Setup ran outside run_step and so incremented nothing: an index outage
        # left the cached tools in place, every check ran against a stale
        # environment, and the run still printed "CI PASSED".
        echo "!!! ERROR: dependency install failed for Python ${ver} -- its checks did NOT run against the intended environment."
        echo
        failures=$((failures + 1))
        continue
    fi
    printf '%s' "$want" > "$stamp"

    run_step "[$ver] Checks (scripts/gate.sh python)" env PATH="$venv/bin:$PATH" scripts/gate.sh python
done

# Mirrors ci.yml's js-lint job (CL-0077). A missing Node is a failure, not a
# skip, for the same reason a missing matrix Python is.
if command -v npm >/dev/null 2>&1; then
    if npm ci --silent --no-audit --no-fund; then
        run_step "Checks (scripts/gate.sh js)" scripts/gate.sh js
    else
        echo "!!! ERROR: npm ci failed -- the JavaScript lint did NOT run."
        failures=$((failures + 1))
    fi
else
    echo "!!! ERROR: npm not found -- CI's js-lint job is NOT mirrored. Install Node.js."
    failures=$((failures + 1))
fi

if [ "$failures" -ne 0 ]; then
    echo "CI FAILED: $failures step(s) failed — fix before pushing."
    exit 1
fi
if [ -n "$unobtainable" ]; then
    echo "CI INCOMPLETE: could not obtain Python(s):$unobtainable — those matrix jobs did"
    echo "NOT run, so this is not a mirror of CI. Treat as a failure, not a pass."
    exit 1
fi
echo "CI PASSED: all checks green across the full Python matrix ($CI_PYTHONS)."
