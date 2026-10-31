# Cold review of the review-readability fixes: closure ledger

Roadmap item CL-0114 (corrected), queued follow-up CL-0121.

| finding | disposition | was -> now or why or id |
|---|---|---|
| google_sync.py Step 3 `clean_push` | fixed | held the baseline for any `result.skipped` or scope error, so a first sync with a refused create left it NULL and a create Google always refuses held it forever -> held only when an edit to a linked contact is left unpushed (an update failed, or a scope refusal while linked updates were waiting); `_push_local_changes` returns that signal and `result.skipped` stays the user-visible count. Pull skips never counted in `result.skipped` (it is only incremented in the push), so that suspicion was not a defect. Red: 3 of 5 new tests failed (first-sync refused create, refused create with a baseline, scope refusal with nothing dirty linked). Existing test `test_a_skipped_push_keeps_the_old_baseline` still holds and was not changed. |
| residual cost of the hold; `push_no_time` not retried | queued | CL-0121: per-contact pending-push marker; needs a migration and a two-way spec section 9 amendment. The spec lines saying `last_synced_at` advances only on a clean finish (partial run, and the test list) are unchanged until then. |
| google_sync.py revoke `except (OSError, ValueError)` | fixed | `http.client.HTTPException` escaped, so the local token stayed -> caught. Red: BadStatusLine from urlopen left token.json in place. |
| import_export.py vCard loop / `importer.unique_label` | fixed | a 64-character label numbered to 66 characters, `valid_field_name` refused the card -> the base is cut so the numbered label fits `MAX_CF_NAME_LEN`; CSV shares the function. A card or row over `MAX_CUSTOM_FIELDS` was refused whole (CSV shares this) -> `_import_rows` drops the extras and warns, naming it. Red: 4 new tests failed. |
| routes/contacts.py `selected_ids` | fixed | 4300+ digits passed `isdecimal` and `int()` raised ValueError (500) -> ignored, as the docstring says, along with anything past SQLite's largest integer. `bulk_delete` and `merge_preview` both call it. Red: helper and POST test raised ValueError. |
| models.py comment "Each also owns its sync_lookup and _mark_edited calls" | fixed | false for `google_sync._upsert_person` (INV-1) -> comment says so. |
| other files | unchanged | `routes/contacts.py` changed only in `selected_ids`; `routes/import_export.py` only in `_import_rows` and one comment; nothing else was touched. |
