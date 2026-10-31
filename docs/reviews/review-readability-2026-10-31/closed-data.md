# Lane 01 (data) closed -- CL-0111

| finding (file:line) | disposition | was -> now, or why, or roadmap id |
|---|---|---|
| photos.py:137 HIGH, docstring vs ensure_private_dir/mkstemp | fixed | both calls were outside the try, so a GET could 500; now inside it via `_atomic_write`. Red: OSError escaped `avatar_filename`. |
| photos.py:134 "no thumbnail is left" | fixed | docstring now says what happens: decode failure removes the stale thumb, write failure keeps the previous one. Red: old thumb survived an undecodable replacement. |
| models.py:826 VALID_CONTACT_TYPES HIGH | fixed | constant moved to config.py (settings cannot import models); models, importer, settings, routes/contacts, routes/merge, routes/import_export import it. Comment names the SQL CHECK and the templates (frontend lane). No red run: nothing observable changes. |
| models.py:863 five custom-field inserts, three core-field writes | fixed | `insert_custom_fields` used in models (4) and google_sync (1); comment above create_contact lists every core-field write site. No red run: nothing observable changes. |
| models.py:28 MAX_CUSTOM_FIELDS comment | fixed | comment names static/app.js for that cap. |
| models.py:811 "every caller" | fixed | docstring says google_sync._upsert_person bypasses it (the caps themselves are routes-sync's). |
| models.py:16 tag caps "choke-point" | fixed | comment says callers must normalise first. |
| db.py:36 comment | fixed | states the idempotent-migration rule. |
| importer.py:135 nameless CSV row | queued | comment added at the check; behaviour needs a decision: CL-0112. |
| importer.py:141 / import_export.py:143-149 repeated label | fixed | vCard route dropped later values; now uses `importer.unique_label` (renamed from `_unique_label`, no other users, no spec cites it). Red: only `{'Nickname': 'Zee'}` stored. |
| models.py:1026 import_contact size | fixed | split into `_find_import_match`, `_insert_imported`, `_fill_existing`; existing import tests cover it. No red run: nothing observable changes. |
| vcard.py:276 card dict | fixed | `parse` docstring documents the keys and the first/last rule; unfolding is `_unfold`. No red run: nothing observable changes. |
| vcard.py:335 hand-written X-LABEL | fixed | calls `_param_value`; skips `_label` on purpose (route sanitises), noted in a comment. |
| photos.py:159 temp-write copy | fixed | `_atomic_write` raises; thumbnail catches. Existing CL-0071 tests cover it. |
| photos.py:38 three format lists | fixed | comment above `_MIME` covers all three. |
| models.py:422 find_all_duplicates | fixed | one `_DUPLICATE_COLUMNS`; the name group now sorts NOCASE like the other two (harmless within a same-name group). Not a shared fetch helper: the three queries differ in WHERE/JOIN. |
| models.py:448 history comments (also 87, 215, 381) | fixed | rewritten as the current rule. The comment at 87 was a docstring tail. |
| models.py:180 docstring | fixed | says it returns the whole SELECT. |
| models.py:1135 profile shapes | fixed | docstring names the list and the old dict. |
| models.py:515 `:prev_sync` | fixed | docstring says `:prev`. |
| models.py:780 `_validate_custom_field_names` name | dismissed | frozen specs cite the name (import-export spec); docstring now says it validates count, value length and names. |
| models.py:548 `_BIRTHDAY_RE` underscore | dismissed | rename is tidying and the name is imported by two modules; comment says it is shared and what changes if it is edited. |
| vcard.py:315 first vs last value | fixed | stated in the `parse` docstring. |
| importer.py:100 guard vs cells[i] | fixed | entries past the headers are dropped up front; guard removed. Red: IndexError. |
| phoneutil.py:13 lenient rule | fixed | comment gives the reason and names the twin. |
| Lead photos.py:143 | fixed | same as the HIGH. |
| Lead photos.py:202 stale thumbnail | fixed | same as the second photo row. |
| Lead photos.py:203 delete_photo PermissionError | dismissed | the route catches OSError and the database keeps naming the old extension, whose file the failed delete left in place; only a stray new file remains. |
| Lead importer.py:115 IndexError | fixed | same as importer.py:100. |
| Lead importer.py:135 empty name | queued | CL-0112. |
| Lead google_sync.py:806 no length caps | dismissed | cap work is routes-sync's; the models.py:811 docstring now records the bypass. |
| Lead google_sync DELETE case-sensitive vs NOCASE index | queued | CL-0113 (not reproduced; the obvious fix also deletes a user's field). |
| Lead import_export.py:159-162 "already counted" | dismissed | the shared import loop and summary are routes-sync's. |
| Lead import_export.py:143-149 lost label | fixed | same as the repeated-label row. |
| Lead vcard.py:331 several NOTE lines | dismissed | keeps the last on purpose; the `parse` docstring states the rule. |
| Lead db.py:57 no encoding | fixed | `encoding='utf-8'`; migrations 006 and 007 hold non-ASCII. Red: decode error under an ASCII locale with UTF-8 mode off. |

Sweep: searched `_unique_label`, `VALID_CONTACT_TYPES`, `insert_custom_fields`, `_write_thumbnail`, `choke-point`, `executemany` across code, README, DESIGN.md, CLAUDE.md and docs/standards; no stale reference found. Dated specs and reviews were left as records.

Gates: full `pytest tests/` (532 passed) and `ruff check .` green on every commit. `local-ci.sh`, mypy, djlint and ESLint were not run (the main session runs local CI before the push).
