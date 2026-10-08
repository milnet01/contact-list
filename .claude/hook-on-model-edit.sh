#!/usr/bin/env bash
#
# hook-on-model-edit.sh — PostToolUse hook for Contact_List.
#
# When Claude edits models.py or anything under migrations/, run the
# pytest suite asynchronously and use the asyncRewake mechanism to wake
# the model only if tests fail. Schema and model layers are tightly
# coupled to SQLite (weak runtime validation), so a regression here is
# expensive — pytest runs cheap.
#
# Wired in via .claude/settings.json:
#     PostToolUse → matcher Edit|Write → command bash <this script>
#                   asyncRewake: true → exit 2 wakes the model
#
# Stdin: PostToolUse JSON. Short-circuit unless touched file is in scope.
# Stdout: nothing on pass / silent skip; pytest output on fail (becomes
#         the rewake message).
# Exit: 0 on pass / silent skip, 2 on test failure (wakes model).

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

file=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)
case "$file" in
    */models.py|models.py) ;;
    */migrations/*|migrations/*) ;;
    */db.py|db.py) ;;
    *) exit 0 ;;
esac

# Pick a python: prefer the project's venv (created by run.sh), fall
# back to system python3. If neither has pytest, silently no-op rather
# than spam the model with "pytest not installed" every edit.
if [ -x "$PROJECT_ROOT/venv/bin/python" ]; then
    PY="$PROJECT_ROOT/venv/bin/python"
else
    PY="python3"
fi
if ! "$PY" -c 'import pytest' 2>/dev/null; then
    exit 0
fi

cd "$PROJECT_ROOT" || exit 0
output=$("$PY" -m pytest tests/ -q --tb=short 2>&1)
status=$?

if [ "$status" -eq 0 ]; then
    exit 0
fi

# Failure — emit pytest output as context for the rewake.
printf '%s\n' "$output"
exit 2
