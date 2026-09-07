# Lane 1 — data-layer (models.py, db.py, migrations/*.sql)

## Critical (0) — nothing found
## High (0) — nothing found

## Medium (6)
- [dim 11] db.py:76 — `with open(os.path.join(migrations_dir, filename)) as f:` — no encoding=, so migration files decode with locale.getpreferredencoding(False). Four migrations contain U+2014 em-dashes in comments (005_photos.sql:4, 006:3, 007:4, 008:9). Under an ASCII locale (LANG=C/POSIX — default for systemd units, cron, minimal containers) this raises UnicodeDecodeError inside init_db and the app cannot start. ruff PLW1514 is outside the configured E4,E7,E9,F select. fix: Path(migrations_dir, filename).read_text(encoding='utf-8'). [tool: ruff]
- [dim 5] models.py:146-149 + models.py:65 — get_letter_counts uses the Python callback first_letter registered in db.py:34. SQLite cannot index an application-defined function, so this is a full table scan invoking Python once per contact. routes/contacts.py:153 calls it on EVERY /contacts render; the letter filter at models.py:65 scans the same way. DESIGN 7.1 targets <100ms at 10k contacts; 7.2 requires indexes on WHERE/ORDER BY columns. fix: stored first_letter column maintained by trigger, indexed.
- [dim 2] models.py:155-158 — export_contacts does .fetchall(). DESIGN 7.2 requires streaming responses for CSV/vCard export using generators, not full in-memory buffers. CSV export shipped. routes/import_export.py:42-54 builds io.StringIO and returns getvalue(); vCard export at :203 issues a get_custom_fields query per contact. CODE is the wrong side. fix: return the cursor, wrap a generator in Response(stream_with_context(...)).
- [dim 9] db.py:35-37 — PRAGMA journal_mode=WAL with synchronous=NORMAL does not fsync at commit, so power loss can roll back transactions already reported saved. DESIGN 3 claims ACID; nothing records durability being traded for speed. fix: synchronous=FULL on the write path, or record the trade in DESIGN 7.2.
- [dim 5] models.py:188-196 — per-row phoneutil.normalize_e164 over all phone-bearing rows on every contact create and update; phonenumbers.parse with no caching. find_all_duplicates (models.py:252-259) does the same for /contacts/duplicates. fix: store the E.164 form in an indexed column.
- [dim 4] models.py:548-561 vs routes/contacts.py:76 — _validate_custom_field_names documents itself as enforcing the contract for every caller but does not enforce a COUNT. The 50-field cap exists only at routes/contacts.py:76. The CSV/vCard import path builds its own list at routes/import_export.py:76-87 and reaches import_contact with no cap, so one crafted vCard writes unbounded custom_fields rows. Tags are capped in the model (MAX_TAGS) and custom fields are not — the two copies diverged. fix: MAX_CUSTOM_FIELDS = 50 enforced in _validate_custom_field_names.

## Low / Info
- [dim 2] DESIGN 4 vs migrations — shipped and undocumented: settings (003), import_profiles (004), contact_photos (005), contact_favourites (007), schema_version (db.py:58-63). DOCUMENT is the wrong side; hand to review-contract.
- [dim 4] models.py:190 vs models.py:254 — same "phone-bearing rows" predicate, one patched with the empty-string guard and one not.
- [dim 5] models.py:105 — COUNT(*) wraps a query carrying three correlated subquery columns. Could not confirm SQLite elides them. fix that removes doubt: _build_contact_query returns (where_clause, params); count becomes SELECT COUNT(*) FROM contacts <where>.
- [dim 5] migrations/002_add_indexes.sql:3 — idx_contacts_email is never usable: every email lookup wraps the column (LOWER(email) at models.py:241 and :716) and search uses leading-wildcard LIKE. Maintained on every write, serves nothing. idx_contacts_phone does have a user.
- [dim 7] models.py:596 and :737 — assert contact_id is not None / assert new_id is not None in shipped application code; vanish under python -O. The FP-ledger S101 entry says hits are all in tests/, no longer true of models.py. [tool: ruff]
- [dim 2] models.py:123 — favourites pinned above every sort unconditionally; DESIGN 9.1 sort/dir table describes neither the pin nor its precedence. Document side likely.
- [dim 16] db.py:50-83 — init_db has no exception handling and the final commit sits outside the loop. Two copies started simultaneously against a fresh DB both run migrations; the second's INSERT INTO schema_version hits the PK and dies with a raw traceback at boot. First-run only.
- [dim 9] models.py:712-730 and :809-819 — match/existence SELECTs run before their `with db:` block, so the row set decided on is not the row set written. Single-process, small window.
- [dim 5] models.py:808 — placeholders join with no bound on loser_ids; over SQLITE_MAX_VARIABLE_NUMBER gives an opaque sqlite3 error rather than a ValueError.
- [dim 2] models.py:410 — age computed as next_date.year - int(year); _BIRTHDAY_RE accepts any four digits, so 0000-05-01 yields an age near 2026 and a future year yields a negative age.
- [dim 2] db.py:2,68-76 — os.listdir/os.path.join/bare open against python.md's pathlib preference.
- [dim 4] models.py:461 — db.commit() inside set_favourite while siblings set_contact_photo (:417) and clear_contact_photo (:439) carry docstrings saying they must NOT commit because Google-sync calls them inside a SAVEPOINT (CL-0045). Latent trap, no current sync-side caller.
- [dim 3] INFO — both named traps checked. sql-fstring: all six f-string SQL sites enumerated (models.py:105,123,174,190,199,812) interpolate structure only; :812 is NOT in the ledger and is new. The allowed_sorts whitelist holds for every call path including the settings-sourced default. migration-idempotency: the db.py:77-80 claim holds against all eight files.
- N/A: 2b, 8, 10, 12, 13, 15, 17 (each with a one-line reason in the lane's return).

## Open questions
1. Is synchronous=NORMAL a decision? Nothing in DESIGN mentions it and 3 claims ACID.
2. Should export_contacts stream, or should DESIGN 7.2 drop the streaming rule?
3. Was is_favourite DESC meant to override an explicit ?sort=?

## 3 items to fix first
1. db.py:76 add encoding='utf-8' — only defect that stops the app starting; environmental trigger no current test surfaces.
2. models.py:146-149 / db.py:34 index the first letter — most-travelled path, measured against a written 7.1 target, degrades linearly.
3. models.py:548 move the 50-field cap into _validate_custom_field_names — the docstring already promises it and the import path bypasses it.
