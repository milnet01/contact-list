# DESIGN.md — review-contract loop log

DESIGN.md carries no loop log of its own, so its gate rows live here. An
earlier gate (commit `d13872f`, §3) recorded itself in its commit message and
is not back-filled.

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Verified | Fixed | Outcome |
|------|------|-------|----|----|----|----------|-------|---------|
| 1 | 2026-09-28 | 2 | 1 | 2 | 0 | 3 | 3 | Gate armed by CL-0065's new §6.4 Output Handling and the rewritten §6.3 process-control bullet. Genre: standard. **One loop only, at the user's standing instruction** — not run to convergence. Both lanes held Q1–Q3. Both found that §6.1's field-name rule, `^[a-zA-Z0-9_ ]{1,64}$` applied with `re.match`, accepts a trailing newline — measured: `valid_field_name('abc\n')` returned True — which made §6.4's claim that an unescaped X-LABEL cannot carry a line break false. The doc now requires a whole-string match, and `models.valid_field_name` uses `fullmatch`, with a test red before the change. Both lanes found §6.3's "all versions pinned" contradicting §3's major-cap policy (§5's tree comment too). One lane found §7.2's "indexes on all columns used in WHERE/ORDER BY" contradicting §4.1's deliberate phone gap; §7.2 is narrowed, and the unindexed created/updated sort is recorded with its measured cost (about 1 ms a page at 10k contacts). Two of three findings lie outside the armed change, fixed because no loop remains. Open questions resolved clean, not tallied: created/updated are app-generated; the photo route sets no header from contact data; `Popen` takes a list with no `shell=True`. Neither lane arrived with a git snapshot. |
