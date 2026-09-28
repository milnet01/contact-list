# CLAUDE.md (project) — review-contract loop log

CLAUDE.md loads into every session, so its review rows live here rather than in it.

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Verified | Fixed | Outcome |
|------|------|-------|----|----|----|----------|-------|---------|
| 1 | 2026-09-28 | 2 | 1 | 0 | 1 | 2 | 2 | Gate armed by CL-0081's new bullet in "Verifying a launch by hand". Genre standard. **One loop only, at the user's standing instruction.** Both lanes held Q1–Q3. One lane found the new assertion checks `config.Config.DATABASE`, which `create_app(test_config)` never reads, and nothing checked the config folder, fixed at import; it now asserts `config._CONFIG_DIR` and the database the app will open, with HOME set before `config` is imported. One lane found the pre-existing port-poll command used `$1`, empty when pasted, so it waited 90 s and reported a live server as down; it now sets `port=`. Fixed although outside the armed change, since no loop remains. The token-rewrite claim was checked in `google_sync._load_credentials` (refresh when expired, then `_save_credentials`) and narrowed to "an expired token". Neither lane arrived with a git snapshot. |
