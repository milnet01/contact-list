#!/usr/bin/env bash
# Verify the app version is in lockstep across the files that carry it.
# Source of truth: APP_VERSION in config.py. The top-most CHANGELOG heading must
# match it. The /bump recipe (.claude/bump.json) runs this as its post_check, and
# the release tag pushed to CI must be v<that version>.
set -euo pipefail
cd "$(dirname "$0")/.."

# `|| true`: under set -e a grep that matches nothing would end the script here,
# before the diagnostics below that name the problem (CL-0078).
code_ver="$(grep -oE "APP_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'" config.py | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)"
# First "## [X.Y.Z]" heading in the CHANGELOG (skips "## [Unreleased]").
log_ver="$(grep -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)"

if [ -z "$code_ver" ]; then
  echo "drift: could not extract APP_VERSION from config.py" >&2; exit 1
fi
if [ -z "$log_ver" ]; then
  echo "drift: no '## [X.Y.Z]' release heading found in CHANGELOG.md" >&2; exit 1
fi
if [ "$code_ver" != "$log_ver" ]; then
  echo "drift: config.py APP_VERSION ($code_ver) != top CHANGELOG version ($log_ver)" >&2
  exit 1
fi
echo "version lockstep OK: $code_ver"
