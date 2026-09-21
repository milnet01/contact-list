# CLAUDE.md — the reasoning behind the rules

`CLAUDE.md` states what is true now and what a breach looks like. The
arguments that settled those rules live here, so the instruction file stays
short enough to read every session. Nothing here is an instruction. If a
line here and a line in `CLAUDE.md` disagree, `CLAUDE.md` governs.

## Why `local-ci.sh` must mirror `ci.yml`

`local-ci.sh` runs the same Python matrix, the same dev-tool pins and the
same checks in the same order as `ci.yml`. It fetches any matrix Python the
machine lacks via `uv`. That is what makes a local pass mean every CI job
would pass, rather than every job the machine happened to be able to run.

This is why a Python version it cannot obtain is a failure and not a
warning. A green light that silently skipped part of the matrix is worse
than no light: it is the same signal as a real pass, and it is wrong.

Landed in *"CI: make local-ci.sh mirror the full matrix, and enforce it
before every push"*.

## Why documentation-only pushes skip the local gate

The gate exists to catch what CI would catch. When every changed file is a
`*.md` or sits under `docs/`, no code changed, so there is nothing for CI to
catch and nothing for the gate to protect. The skip is automatic rather than
a judgement call, because a judgement call is what gets taken on a tired
Friday for a change that was not documentation-only.

## Why the dependency budget and the line length are not written in `CLAUDE.md`

Both are numbers, and a number copied into a second file goes stale there
first. `DESIGN.md` §3 owns the dependency budget and the exception register.
`pyproject.toml` owns the line length, and `ruff` enforces it. `CLAUDE.md`
names the rule and points at whichever file holds the figure.

## Why the launch-verification traps keep their reasons

Each trap in `CLAUDE.md` § *Verifying a launch by hand* carries the failure
it prevents — a fixed `sleep` giving a false negative, a foreground launch
never returning, an unobserved browser-open proving nothing. That clause is
not background. It is what a breach looks like, and a reader who has just
been bitten needs it in the file they already have open.
