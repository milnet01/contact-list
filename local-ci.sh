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

# Keep in lockstep with ci.yml's matrix.python-version.
CI_PYTHONS="3.12 3.13 3.14"
# Keep in lockstep with ci.yml's dev-tool pins (ruff + mypy; not app runtime deps).
# These cap the MAJOR/MINOR only so a breaking release can't land unreviewed; raise
# them promptly once a new one is vetted (DESIGN.md §3 — dependencies track latest).
DEV_TOOLS=("ruff~=0.16.1" "mypy~=2.1")

VENV_ROOT="$APP_DIR/.ci-venvs"
failures=0
unobtainable=""

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
    want="$("$py" -c 'import sys;print(sys.version)' 2>&1)|${DEV_TOOLS[*]}|$(sha256sum requirements.txt | cut -d' ' -f1)"
    if [ -d "$venv" ] && [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
        echo "    inputs changed since this venv was built — rebuilding it"
        rm -rf "$venv"
    fi
    if [ ! -d "$venv" ]; then
        "$py" -m venv "$venv"
    fi
    "$venv/bin/python" -m pip install --quiet --upgrade pip
    "$venv/bin/pip" install --quiet -r requirements.txt
    "$venv/bin/pip" install --quiet "${DEV_TOOLS[@]}"
    printf '%s' "$want" > "$stamp"

    run_step "[$ver] Lint (ruff)"       "$venv/bin/ruff" check .
    run_step "[$ver] Type-check (mypy)" "$venv/bin/mypy"
    run_step "[$ver] Test (pytest)"     "$venv/bin/pytest"
done

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
