# Dependency sweep — 2026-08-06

A dated record of one sweep. It lived in `DESIGN.md` §3 until 2026-09-07 and was
moved here: a current-versions table inside a standard is wrong from the first
upstream release and nothing announces it, which is the same reasoning §3 used
to drop its own *Latest available* column. It proved itself within a month — the
`softprops/action-gh-release` line below went stale when that action was
SHA-pinned to v3.0.3 on 2026-09-07.

**Read this as history, not as current state.** Re-derive current versions with
the sweep commands in `DESIGN.md` §3; they are the only form that can be trusted.

**Last full sweep: 2026-08-06.** All four scopes checked, everything at latest:

- **Runtime + test:** flask 3.1.3, google-api-python-client 2.198.0, google-auth
  2.56.3, google-auth-oauthlib 1.4.0, google-auth-httplib2 0.4.1, phonenumbers
  9.0.36, pillow 12.3.0, pystray 0.19.5, pytest 9.1.1.
- **Dev/CI tools:** `ruff~=0.16.1` (was `~=0.15.0` — an undocumented below-latest
  cap, corrected), `mypy~=2.1` (admits the current 2.3.0).
- **Actions:** checkout@v7 (v7.0.1), setup-python@v7 (was @v6, a full major
  behind — bumped in both `ci.yml` and `release.yml`), upload-artifact@v7
  (v7.0.1), download-artifact@v8 (v8.0.1), softprops/action-gh-release@v3
  (v3.0.2). Runner images all `*-latest`.
- **Python runtime:** CI matrix is 3.12 / 3.13 / **3.14** (3.14 added this sweep;
  current stable is 3.14.7). `local-ci.sh`'s `CI_PYTHONS` mirrors it. Note that
  3.12 and 3.14 are not installed on the current dev machine, so a local run
  mirrors only the 3.13 job and says so loudly.

## Later corrections to this record

- **2026-09-07** — `softprops/action-gh-release` is no longer `@v3`. It is
  SHA-pinned to `efb35369e0ad2afab669f228072c1b0d510eae64` (v3.0.3), because it
  is the one third-party action in the tree and it runs in the job holding
  `contents: write`. The GitHub-owned actions stay on major tags.
- **2026-09-07** — the note that a local run "mirrors only the 3.13 job" was
  true when written and is not now. `local-ci.sh` fetches any missing matrix
  interpreter via `uv`, and fails rather than passing when it cannot.
