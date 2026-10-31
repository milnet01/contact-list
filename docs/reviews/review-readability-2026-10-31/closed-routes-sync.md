# Lane 02 routes-sync: closure ledger

Roadmap item CL-0114. Lane file: lane-02-routes-sync.md.

| finding (file:line) | disposition | was -> now, or why, or roadmap id |
|---|---|---|
| google_sync.py:354 Step 3 comment | fixed | comment claimed a clean finish; code advanced `last_synced_at` after a scope 403 or skips. The two-way spec (partial run) promises a retry, so the code now advances it only on a clean push and the comment says so. Red: baseline moved to now, retry pushed 0. |
| import_export.py:160 "CSV counts the same" | fixed | comment was false; removed with the shared loop |
| import_export.py:260 / import.html:78 diverged refusal handling | fixed | one `_import_rows` for both paths counts and names each refusal; label "Skipped (blank rows)" -> "Skipped", plus a warning for blank CSV rows. Red: no "Skipped: 1" after a refused CSV row. |
| google_auth.py:18 hand-kept paths and token write | fixed | paths from `Config`; `config.write_private_text` replaces both copies; `CREDS_DIR` removed (no other users), `CREDS_FILE`/`TOKEN_FILE` kept (a spec cites `CREDS_FILE`). Test for the helper. |
| google_auth.py:35 "inlined to stay standalone" | fixed | false claim and copies deleted |
| google_sync.py:737 bare INV/section numbers | fixed | module note names the two-way spec; photo citations say "photos spec". `DESIGN.md §9` citation was already explicit. models.py:534 INV-6 is outside this lane's files and unchanged. |
| google_sync.py:256 managed-field set kept in several places | fixed (part) | pull list now `_MANAGED_FIELDS + photos` (`_PULL_FIELDS`); comment corrected. The push-body branches and import branches stay: each is per-field logic, not a list to derive. no red run: nothing observable changes |
| google_sync.py:814 case-sensitive delete | fixed | CL-0113: reproduced (IntegrityError, contact skipped); `LOWER(field_name)`. Red run seen first. |
| google_sync.py:270 no Step 1 banner | fixed (banner only) | Step 1 banner added; no split: the two-way spec pins "a three-step orchestration inside the existing function" |
| routes/contacts.py:173 literal 200 (and models.py:261, settings.html:92) | fixed | all read `Config.MAX_CONTACTS_PER_PAGE`. Red: 5 rows against a ceiling of 3. |
| routes/contacts.py:191 "reuse both" | fixed | comment says the route re-derives total_pages and the page |
| google_sync.py:63 `has_credentials` name | fixed | docstring, no rename (specs cite it) |
| import_export.py:188 hard-coded "1 MB" | fixed | message from the limit in force (`config.megabytes_text`). Red: message kept old figure. |
| routes/contacts.py:312 hard-coded "4 MB" | fixed | from `photos.MAX_PHOTO_BYTES`; the form hint in contact_form.html too, via a `photo_limit` template variable. Red likewise. |
| google_sync.py:133 docstring vs catch-all | fixed | `_load_credentials` docstring names the catch-all. no red run: nothing observable changes |
| google_sync.py:276 guard comment, dead `synced = 0` | fixed | comment states what the guard proves; reset removed. no red run: nothing observable changes |
| google_sync.py:566 two error readers | fixed | `_api_error_parts` serves both checks. no red run: nothing observable changes |
| routes/contacts.py:116 contact-type literals | dismissed | already done by the data lane (`VALID_CONTACT_TYPES` in config) |
| routes/contacts.py:474 two `selected` parsers | fixed | `selected_ids` used by bulk delete and merge. no red run: existing tests cover |
| routes/merge.py:136 nested helper | fixed | module-level `_preserve_extra` with explicit arguments; existing test covers the preserved phone. no red run: nothing observable changes |
| routes/merge.py:51 why lowest id survives | fixed | comment (states what is known; Google links are not considered, see CL-0118) |
| routes/merge.py:102 silent type fallback | fixed | comment gives the reason |
| google_auth.py:14 false import claim | fixed | corrected |
| routes/sync.py:27 stale comment | fixed | second half deleted |
| routes/contacts.py:375 (and 226, 314) history comments | fixed | rewritten as the rule; google_sync.py 281 and 496 likewise; import_export.py 158 removed with the loop |
| google_sync.py:451 shared underscore names | fixed (comments) | `_BIRTHDAY_RE`, `_normalize_tags`, `_safe_ref` say they are shared; no rename (three specs cite them) |
| routes/contacts.py:59 unused `log` | fixed | removed, with the `logging` import |
| lead google_sync.py:358 | fixed | see Step 3 row. Hazard noted in the code: a contact that fails every time holds the baseline back, so each sync re-examines every edit since the last clean one. |
| lead google_sync.py:814 | fixed | CL-0113 |
| lead google_sync.py:806 pull has no field caps (assigned) | queued | CL-0115. Measured: `update_contact` then raises "Name exceeds 200 characters". Truncating loses data, so no caps added; `models._validate_field_lengths` docstring now states the consequence. |
| lead google_sync.py:177 `creds.revoke` | fixed | real bug: google-auth 2.56.3 `Credentials` has no `revoke`; the AttributeError was swallowed, so Disconnect never revoked. Now posts the stored token to Google's revoke endpoint. Red: no request sent. |
| lead google_sync.py:166 legacy token never revoked | fixed | same change: the token file is read directly, so legacy and expired tokens are revoked |
| lead google_sync.py:572 any 403 means "reconnect" | queued | CL-0117 |
| lead routes/merge.py:118 uncapped preview / extras over cap | queued | CL-0118 (also notes merge ignores Google links of losers, unchecked) |
| lead routes/sync.py:93 no counts on error | queued | CL-0116 |
| tool? routes/contacts.py:59 unused variable | fixed | see `log` row |
| dismissed candidates (dup:5bfe..., c2f5..., 2a2e..., f5c3..., a87b...) | dismissed | the lane's own reasons stand; not re-examined |

Sweep: searched README.md, DESIGN.md, CLAUDE.md, docs/*.md and the code for "blank rows", `creds.revoke`, `CREDS_DIR`, the literals "1 MB", "4 MB" and 200 as a page ceiling, and `_save_credentials`. Found: DESIGN.md states the unchanged default of 200 per page (a value, not a copy of the constant's use; left). The roadmap mentions `_save_credentials` in a dated item (left; name unchanged). Nothing else stale. DESIGN.md §6.2 and §9 call Disconnect a revoke, which is now true.

Gates: `./venv/bin/python -m pytest tests/ -q` (542 passed) and `ruff check .` green at every commit. `local-ci.sh` not run (main session does). JS and the frontend lane's files untouched, except the `max` attribute in settings.html and the photo hint in contact_form.html.
