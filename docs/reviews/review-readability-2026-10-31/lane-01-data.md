## Files read
- `models.py`: 1159 / 1159 lines
- `db.py`: 64 / 64
- `photos.py`: 243 / 243
- `phoneutil.py`: 35 / 35
- `vcard.py`: 340 / 340
- `importer.py`: 153 / 153

## What I started with
- The global `~/.claude/CLAUDE.md`.
- A note giving the user's email address.
- A session-start notice about Ants MCP.
- The environment block (platform, date, model).
- No project `CLAUDE.md` beyond the one line in the brief, no memory index and no git snapshot.

I found no disagreement between the brief and my lane file.

## Summary
This code is where the contact list keeps its data. It saves, finds, merges and deletes contacts in a small database, and it keeps a side table so the A–Z bar and duplicate checks stay fast. It stores contact photos as files and makes small thumbnails of them. It also reads and writes vCard files and reads CSV files, so contacts can move in and out of other apps. Google sync lives elsewhere but writes to the same tables, bypassing several of the rules these files say apply to everyone.

## Findings

[Q4] HIGH `photos.py:137` — `ever 500-ing where the old read-only route could not.` — The docstring promises every filesystem failure returns `False`, but `ensure_private_dir` (line 143) and `mkstemp` (line 152) sit outside the `try`. A full disk or unwritable folder therefore raises out of `avatar_filename` and `routes/contacts.py:349`, which shows no guard in the lines I read. A stranger adding another caller would leave it unguarded on this promise. *"Either way no thumbnail is left"* (line 134) is also false: when a same-extension replacement fails to decode, the old thumbnail stays. — Fix: bring those two calls inside the `try` and correct the "no thumbnail is left" sentence.
Cost: one edit — Searched: `docs/` for `_write_thumbnail`. `docs/specs/2026-07-04-photo-thumbnails-design.md` names it, but no name or signature changes.
Searched: `avatar_filename` in non-test `*.py`.

[Q1] HIGH `models.py:826` — `VALID_CONTACT_TYPES = ('individual', 'company')` — This looks like the single source of truth, but only line 832 uses it. A stranger adding a type would change this and the SQL CHECK, then miss the other copies. Each missed copy fails silently: `models.py:211` ignores the filter, `importer.py:144` falls back to the default type, and `routes/merge.py:102` turns the contact into an individual. Other copies are `routes/contacts.py:116`, `routes/import_export.py:235`, `settings.py:59`, and `<option>` lists in `templates/contact_form.html`, `contacts.html`, `settings.html` and `import.html`. — Fix: have the Python sites import the constant, and pass it to the templates or note them beside it.
Cost: one edit — Searched: `docs/specs`, `docs/plans` for `VALID_CONTACT_TYPES`, nothing found.
Searched: the literal pair across the tree, excluding docs, and `value="individual|company"` in templates.

[Q1] MEDIUM `models.py:863` — `'INSERT INTO custom_fields (contact_id, field_name, field_value) VALUES (?, ?, ?)',` — There are five copies of this insert: `models.py:863`, `904`, `1037`, `1080` and `google_sync.py:860`. The `INSERT INTO contacts` has three (`models.py:855`, `1029`, `google_sync.py:819`), as does the core-field `UPDATE` (`models.py:895`, `1060`, `google_sync.py:806`). A stranger adding a core field would change `create_contact` and `_write_contact`, then miss the import and Google paths, and those contacts would silently lose the value. The comments at lines 866 and 909-911 warn about `create_contact` and `import_contact` but never mention `google_sync`. — Fix: one private helper for the custom-field insert, and a comment listing every core-field write site.
Cost: pinned: `docs/specs/2026-07-03-tags-labels-design.md`, the passage on `create_contact`'s own INSERT and custom-field `executemany`. No function name changes, but that text would need checking.
Candidate: dup:4673f142cf56. The custom-field inserts and the 8-parameter signatures really are copies. What differs after them (the tag write, the `with db` wrapper) is explained by comments.
Searched: `INSERT INTO contacts`, `UPDATE contacts` and `INSERT INTO custom_fields` in non-test `*.py`.

[Q4] MEDIUM `models.py:28` — `# These mirror templates/contact_form.html's maxlength values; change both` — The comment sits above all six caps but is true of only some of them. `MAX_CUSTOM_FIELDS` has no maxlength; its copy is `static/app.js:409`. A stranger raising it to 100 would follow the comment, find nothing, and the browser would still stop at 50. The name and value lengths do match the template. — Fix: name `static/app.js` for `MAX_CUSTOM_FIELDS` in the comment.
Cost: one edit — comment only.
Searched: `maxlength|MAX_…` across the tree, excluding `docs/` and `tests/`.

[Q4] MEDIUM `models.py:811` — `"""Bound the core contact fields, for every caller including the importers.` — `google_sync._upsert_person` (`google_sync.py:806-822`, `860`) writes contacts and custom fields directly and calls no validator. A stranger relying on *"every caller"* (also lines 21-27 and 782) would assume a stored name or note is always within its cap. — Fix: state the Google exception in the comment, or validate there.
Cost: one edit — comment only.
Searched: read `_upsert_person` in full.

[Q4] MEDIUM `models.py:16` — `# how many tags one contact may carry. Both are enforced in _normalize_tags,` — It goes on *"single choke-point for every tag write"*, but `create_contact`, `update_contact` and `set_contact_tags` never call it. Only the routes do (`routes/contacts.py:384`, `459`; `routes/merge.py:160`). A stranger passing `tags=` from a new caller would believe the caps hold. The next comment (lines 21-22) praises enforcement in the model, which strengthens the wrong belief. — Fix: say that callers must normalise first and the writers do not check.
Cost: one edit — comment only.
Searched: `_normalize_tags|set_contact_tags` in non-test `*.py`.

[Q4] MEDIUM `db.py:36` — `each statement was IF NOT EXISTS; a future non-idempotent migration could` — This comment implies version tracking makes non-idempotent migrations safe. Lines 58-61 say every migration must stay idempotent anyway, and `docs/specs/2026-07-01-contact-photos-design.md:84` agrees. A stranger writing a migration who stops at the first comment would write one that breaks on a crash re-run. — Fix: cut the top comment to the current rule.
Cost: one edit — comment only.

[Q5] MEDIUM `importer.py:135` — `if not name and not email:` — A CSV row with an email and no name passes, and `import_contact` inserts a contact whose name is `''`. The contact form requires a name (`routes/contacts.py`, `validate_core_fields`), the vCard parser drops nameless cards (`vcard.py:175`), and Google drops them too. No comment says why CSV differs. A stranger would assume every contact has a name, or "fix" one path without knowing whether this is deliberate. — Fix: state the reason, or apply the same rule as the other paths.
Cost: one edit — Searched: `docs/specs`, `docs/plans` for `apply_mapping`, "no name", "nameless", "blank name", "empty name", "name is required": none on this rule.
Searched: `tests/test_import*.py` by pattern, no test row found for this case.

[Q1] MEDIUM `importer.py:141` — `(_unique_label(label, used), val)` — The two import paths treat a repeated custom-field label differently, with no comment naming a reason for the difference. CSV keeps the value under a renumbered label; vCard (`routes/import_export.py:143-149`) silently drops the later value. A stranger fixing lost fields in one path would believe both are fixed, despite the module docstring's *"lives in a single place"*. — Fix: use one rule for both, or comment why they differ.
Cost: one edit — Searched: `docs/specs`, `docs/plans` for `_unique_label`, nothing found.

[Q2] MEDIUM `models.py:1026` — `with db:` — `import_contact` runs lines 987-1088 (102 lines), and the tool's shortlist did not include it. The thread is lost here: one transaction block holds the "create" branch, which returns early, and then falls through to a separate "additive update" flow with a nested function and its own edit marking. A stranger adding a rule for "imported contacts" could easily put it in only one branch. — Fix: split into find-match, insert-new and fill-existing steps.
Cost: one edit — Searched: `docs/` for `import_contact`. `docs/specs/2026-07-01-import-export-merge-design.md:179` and the tags spec name it, but its name and signature stay.

[Q2] MEDIUM `vcard.py:276` — `card = {` — This 13-key dict is the contract with `_finalize`, which is defined about 100 lines above it, and nothing describes it. `bday` holds an unescaped value, `adr` a raw one (lines 320, 323), `org` keeps its label in a separate key, and `n_raw`, `n_given` and `n_family` hold one property three ways (re-parsed at lines 171-173). A stranger copying the ADR branch for a new property would keep raw escapes in the stored value. — Fix: split unfolding into its own function and document the card's fields in one place.
Cost: one edit — Searched: `docs/specs`, `docs/plans` for `_finalize`, nothing found; `parse` keeps its name.
Candidate: function_sizes `vcard.py:253:parse`. Length is not the problem; the undocumented dict is.

[Q1] LOW `vcard.py:335` — `if p.upper().startswith('X-LABEL='):` — This is a hand-written copy of `_param_value` (line 221). It differs in two ways: the last value wins rather than the first, and it skips the `valid_field_name` check that `_label` applies. The route sanitises the name later, so no failure results today. A stranger adding quoted-parameter support to `_param_value` would miss this copy. — Fix: call `_param_value` here.
Cost: one edit — Searched: `docs/specs`, `docs/plans` for `_param_value`, nothing found.

[Q1] LOW `photos.py:159` — `except OSError:` — The temp-write, replace and clean-up sequence appears at lines 152-164 and 189-200. Both sites cite CL-0071, so a past fix touched both. A stranger adding a flush-to-disk step to one would miss the other. They differ deliberately: the thumbnail swallows the error, the original re-raises it. — Fix: one atomic-write helper that raises, with the thumbnail catching.
Cost: one edit — Searched: `docs/` for `_write_thumbnail`, `save_photo`. The specs name them, but neither name changes.
Candidate: dup:7cd4cd8b91ec.

[Q1] LOW `photos.py:38` — `_MIME = {` — Three hand-kept lists describe one set of formats: `detect_image_ext`, `_MIME` and `_PIL_FORMAT`. They match today. The comment at lines 45-46 ties only `_PIL_FORMAT` to the set. A stranger adding a format who misses `_MIME` would serve it as `application/octet-stream`. — Fix: extend that comment to cover all three.
Cost: one edit — comment only.

[Q1] LOW `models.py:422` — `"SELECT id, type, name, email, phone FROM contacts "` — `find_all_duplicates` repeats its find-groups-then-fetch-rows block three times, with this column list in each. Sorting has drifted (line 423 uses plain `name`, lines 438 and 460 use NOCASE), harmlessly within a same-name group. A stranger adding a column for the duplicates page would miss one. — Fix: one shared column list and a helper.
Cost: one edit — Searched: `docs/` for `find_all_duplicates`. The merge spec names it, but the name stays.

[Q4] LOW `models.py:448` — `# _phone_key stores NULL for an absent or empty phone, which is what the old` — The current rule is explained through code that no longer exists; the same happens at lines 87-88, 215-218 and 381-383. A stranger has to reconstruct the old code to understand the present. — Fix: state the current rule and leave the history to the commit.
Cost: one edit — comment only.

[Q4] LOW `models.py:180` — `"""Build WHERE clause for contact listing. Returns (query_fragment, params)."""` — It actually returns a complete `SELECT`. A stranger who believes the docstring would prepend their own SELECT. The next few lines correct them. — Fix: reword the docstring.
Cost: one edit — comment only.

[Q4] LOW `models.py:1135` — `"""Return a saved CSV column-mapping profile for this header layout, or None."""` — `mapping` can be a list or a pre-CL-0097 dict, and only `routes/import_export.py:213-216` knows that. The docstring at line 1149 mentions only the list. A new reader of profiles would crash on an old saved one. — Fix: name both shapes here.
Cost: one edit — comment only.

[Q4] LOW `models.py:515` — `'  AND :prev IS NOT NULL AND e.edited_at > :prev',` — The docstring at line 509 calls this parameter `:prev_sync`, which appears in no SQL. A stranger searching for it gets only the comment. — Fix: match the name.
Cost: one edit — comment only.

[Q3] LOW `models.py:780` — `def _validate_custom_field_names(custom_fields: list[tuple[str, str]] | None) -> None:` — It also enforces the field count and the value length. A stranger looking for the value cap would skip it, and might add a second check. — Fix: rename to cover the whole custom-field list.
Cost: pinned: `docs/specs/2026-07-01-import-export-merge-design.md:109`, `184`, `466`.

[Q3] LOW `models.py:548` — `_BIRTHDAY_RE = re.compile(r'^(?:(\d{4})-)?(\d{2})-(\d{2})$')` — The underscore says private, but `vcard.py:20` and `google_sync.py:451` both use it, and `_normalize_tags` is imported by routes in the same way. A stranger could tighten it believing it local, which would silently change vCard export (the BDAY property falls back to X-CL). — Fix: drop the underscore on names used across modules.
Cost: pinned: `docs/specs/2026-07-03-tags-labels-design.md` for `_normalize_tags` (lines 4, 110, 233 and others). `_BIRTHDAY_RE` is unsure, because I did not search the specs for it.

[Q5] LOW `vcard.py:315` — `if card['org'] is None:` — ORG, BDAY and ADR keep the first value, while FN, N and NOTE keep the last, and nothing says why. A stranger cannot tell whether this is deliberate, and `importer.py`'s docstring says *"first value is primary"*. — Fix: one comment stating the rule.
Cost: one edit — comment only.

[Q5] LOW `importer.py:100` — `base = sanitize_field_name(headers[i]) if i < n else ''` — This guard implies a mapping may point past the headers, but line 115 indexes `cells[i]` unguarded for the same `i`. `routes/import_export.py:246-249` never produces such an index. A stranger would trust out-of-range entries to be tolerated. — Fix: remove the guard or handle the case at line 115 too.
Cost: one edit — Searched: `apply_mapping` in `docs/specs`, `docs/plans`, nothing found.

[Q5] LOW `phoneutil.py:13` — `if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):` — The lenient rule has no stated reason, and line 31 repeats it. A stranger tightening one copy would make displayed numbers and duplicate keys disagree. — Fix: one comment giving the reason and naming the twin.
Cost: one edit — comment only.

## Candidates dismissed
- **dup:a87bf7a558c5** — The `models.py:816-820` and `routes/contacts.py:122-126` pair is two copies, and the comment at `routes/contacts.py` explains why both exist. The `is not None` versus truthy difference has no effect, because an empty string has length 0. The different messages are deliberate.
- **function_sizes `vcard.py:167:_finalize`** — Readable; its problem is the dict contract, reported under `parse`.
- **function_sizes `photos.py:167:save_photo`, `photos.py:128:_write_thumbnail`, `photos.py:73:generate_thumbnail`** — Much of their length is docstring and comments, and the flow is linear.
- **function_sizes `db.py:31:init_db`** — Short and linear; the comment problem is reported separately.
- **function_sizes `vcard.py:133:iter_emit`** — Linear, one card at a time.
- **comment_claims `photos.py:33` "~35 px"** — True: `--avatar-size: 2.2rem` (`static/style.css:32`), assuming a 16 px root size.
- **comment_claims `photos.py:34` "~56 px"** — True: `3.5rem` (`static/style.css:419`), same assumption. "256 px stays" is a judgement I cannot fault; the size matches `THUMBNAIL_MAX_PX`.
- **comment_claims `photos.py:35` "~20"** — Cannot be checked by reading; see Not checked.
- **comment_claims `vcard.py:140` "2426 makes"** — Matches my memory of RFC 2426; I did not open the RFC.

## Correctness leads
- `photos.py:143` — `ensure_private_dir` or `mkstemp` raising `OSError` would turn a photo GET into a 500. — Searched: `avatar_filename` callers; `routes/contacts.py:338-354` shows no `try`.
- `photos.py:202` — A same-extension replacement that fails to decode keeps the old thumbnail, so `avatar_filename` shows the previous photo. — Searched: none.
- `photos.py:203` — `delete_photo` catches only `FileNotFoundError`, so a permission error raises after the new file is already in place. The caller may then not record the new extension. — Searched: none; callers not read.
- `importer.py:115` — `cells[i]` raises `IndexError` for any mapping index at or past the header count. — Searched: `apply_mapping` callers; the route cannot produce one.
- `importer.py:135` — A CSV row with an email and no name creates a contact with an empty name. — Searched: `tests/test_import*.py` by pattern; `migrations/001_initial.sql:4` has NOT NULL. I did not read that file's full table definition.
- `google_sync.py:806` — Google pull stores names, notes and phones with no length cap, which may make that contact refuse a later edit. — Searched: read `_upsert_person`.
- `google_sync.py` (the `DELETE FROM custom_fields … field_name IN ('birthday', 'address', 'organization')` in `_upsert_person`) — The match is case-sensitive, while `idx_cf_unique` is NOCASE (`migrations/002_add_indexes.sql:17`). A linked contact with a field named `Birthday` would then hit a uniqueness error on insert. — Searched: `idx_cf_unique`, `field_name TEXT`; how the error is handled upstream was not read.
- `routes/import_export.py:159-162` — The comment says the CSV path *"already counted"* refused rows, but its `except` (lines 259-261) adds a warning and does not increment `skipped`. — Searched: read both loops.
- `routes/import_export.py:143-149` — A repeated vCard label loses its value without a warning. — Searched: read that loop.
- `vcard.py:331` — A card with several NOTE lines keeps only the last. — Searched: none.
- `db.py:57` — `open()` has no `encoding=`. An earlier review (`docs/reviews/2026-09-07-review-code/01-data-layer.md`) reported that this breaks startup on an ASCII locale, and the line is still unchanged. — Searched: found that review through a docs search; migration contents not re-checked.

## Not checked
- **Test bodies:** I read only search rows from them.
- **Candidate search:** my combined search was cut at 120 rows with `next_offset` set, and I did not page on. The unread rows sit past `tests/test_vcard.py`. I filed nothing depending on them, and I dropped a suspicion that `vcard.emit` is called only from tests because I could not back the "only".
- **Docs search:** the first docs search was also cut. I re-ran it excluding reviews and audit reports, and that rerun was cut at 60 rows from offset 39. Those rows are enough for the "pinned" grades above, but they do not show that no further spec names these functions.
- **Search oddity:** a literal `avatar_filename(` search with glob `routes/*.py` returned nothing, while a `*.py` search found `routes/contacts.py:349`. No other finding relies on a `routes/*.py` glob.
- **Could not judge by reading:**
  - The "~20-40 KB" thumbnail size at `photos.py:35`.
  - The DESIGN.md section references.
  - INV-2 of the import spec.
  - CL ticket contents.
  - Whether the `MAX_DUPLICATE_GROUPS` and `MAX_UPCOMING_BIRTHDAYS` callers really report truncation, as `models.py:39-40` says. I did not read those callers.
- **Not opened or re-checked:**
  - The rest of `routes/*`, beyond the passages cited above.
  - `contacts.db` and `~/.config/contact-list/`, per the brief.
  - `static/app.js`, seen only as search rows, so I do not know whether it carries a comment beside its cap.
