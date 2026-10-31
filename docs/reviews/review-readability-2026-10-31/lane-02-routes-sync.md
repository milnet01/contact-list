## Files read
- `google_sync.py`: 865 / 865 lines
- `google_auth.py`: 53 / 53
- `routes/contacts.py`: 514 / 514
- `routes/import_export.py`: 290 / 290
- `routes/merge.py`: 171 / 171
- `routes/settings.py`: 73 / 73
- `routes/sync.py`: 121 / 121

## What I started with
- The review-lane agent file
- The global `~/.claude/CLAUDE.md`
- The user's email, as session context
- A SessionStart note about the Ants MCP verbs
- Environment details: platform, date and model

I had no project `CLAUDE.md`, memory index or git snapshot. My brief and the lane file did not disagree.

## Summary
This is the web side of a personal contact list. It serves the pages for listing, adding, editing, merging, importing and exporting contacts, plus settings and restarting the server. It also does a two-way sync with Google Contacts: it pulls Google's changes, pushes local edits back, and when both sides changed it keeps one copy based on edit times. `google_auth.py` is the small script that opens a browser so the user can grant Google access. It saves the resulting login token to a private file.

## Findings

[Q4] HIGH `google_sync.py:354` — `# --- Step 3: finalise. last_synced_at advances UNCONDITIONALLY on a clean` — A stranger would trust that a failed push does not move the baseline. Nothing tests for a clean finish: after a scope 403 (`result.error` set) or per-contact skips, `_push_local_changes` returns normally and Step 3 still runs. — Fix: make the comment say what the code does, or settle the behaviour (see Correctness leads).
Cost: one edit — comment only, no search owed.

[Q4] HIGH `routes/import_export.py:160` — `# "50 created". The CSV path a few functions down already counted` — The comment says the CSV path uses "the same accounting". It does not: lines 259-261 add a warning but never increment `skipped`. A stranger trusting this would leave the CSV path unfixed, or copy it thinking it was the model. — Fix: correct the comment when reconciling the two paths (next finding).
Cost: one edit — comment only, no search owed.

[Q1] HIGH `routes/import_export.py:260` — `warnings.append(str(exc))` — The refused-row handling has diverged between the two import paths:
- vCard (lines 157-164) counts the refusal and names the card in the warning.
- CSV (lines 259-261) does not count it and names no row.
- `templates/import.html:78` labels the count "Skipped (blank rows)", which is wrong for refused vCards.

A fix to the summary would land in one path only. — Fix: one shared loop over `import_contact` that does the counting, and a template label that fits both.
Cost: one edit — Searched: `_import_vcard_text` in DESIGN.md, docs/specs, plans, standards: no hits. `import_apply` is named in the import-export spec, but the fix does not rename it.
Confirms dup:bf339bbaa94a.

[Q1] HIGH `google_auth.py:18` — `CREDS_DIR = os.path.expanduser('~/.config/contact-list')` — The config directory and both file names are kept by hand here and at `config.py:13` and `config.py:209-210`. The token-write block is also copied (`google_sync.py:146-149` and lines 43-46 here). If a stranger moves the config directory in `config.py`, the auth script keeps writing the token to the old place and the app sees no token. — Fix: take the paths and the private-write helper from `config`.
Cost: one edit — Searched: `CREDS_DIR`, `TOKEN_FILE` in DESIGN.md and docs: `CREDS_DIR` has no hits, and `GOOGLE_TOKEN_FILE` hits are the config key, which does not change. `docs/specs/2026-07-10-standalone-launchers-design.md:227` says `google_auth.py` was unchanged by that work, which does not pin it.

[Q4] HIGH `google_auth.py:35` — `# Inlined rather than importing config, to keep this auth script standalone.` — This is false. Line 16 imports `google_sync`, which imports `photos`, and `photos.py:26` runs `from config import ensure_private_dir`. A stranger would keep the copies above in order to protect a separation that does not exist. — Fix: delete the claim along with the copies.
Cost: one edit — comment only, no search owed.

[Q4] MEDIUM `google_sync.py:737` — `except Exception:  # noqa: BLE001 -- a photo never aborts the import (INV-5); logged` — Bare invariant and section numbers point at different documents:
- INV-5 here is `docs/specs/2026-07-01-contact-photos-design.md:479`, but INV-5 at `google_sync.py:38` is the two-way spec's scope rule (`docs/specs/2026-07-02-two-way-google-sync.md:924`).
- INV-6 at line 661 is the photo spec, while `models.py:534` means the two-way spec.
- Bare `§9` (lines 49, 551) is the two-way spec's error handling, but line 158 cites DESIGN.md §9, which is API/route design.

A stranger looks up the wrong rule, and `docs/reviews/2026-09-07-review-code/05-google-sync.md:23` shows this has already misled a reviewer. — Fix: name the spec in each citation, or once per module section.
Cost: one edit — comment only, no search owed.

[Q1] MEDIUM `google_sync.py:256` — `'names,emailAddresses,phoneNumbers,'` — The managed-field set is kept by hand in these places:
- the pull list (lines 256-257)
- `_MANAGED_FIELDS` (line 379)
- the branches of `_person_body_for_push` (lines 474-512)
- the delete list and import branches in `_upsert_person` (lines 814, 835-856)

Adding a field to the constant changes nothing on the pull or the push body. The comment at line 376, "The only fields the app reads or writes", is also false for the pull, which reads `photos`. — Fix: derive the pull list from the constant plus photos, and correct the comment.
Cost: pinned: `docs/standards/versioning-overrides.md:36` names `google_sync._MANAGED_FIELDS`; `docs/specs/2026-07-01-contact-photos-design.md:236` says `sync_contacts` adds `photos` to `personFields`.

[Q1] MEDIUM `google_sync.py:814` — `"AND field_name IN ('birthday', 'address', 'organization')",` — Matching on field name has diverged. This delete is case-sensitive, because `field_name` has default collation (`migrations/001_initial.sql`). The push lowercases names (line 493), and `models.py:591` and `idx_cf_unique` ignore case. A stranger would assume the delete clears a user's "Birthday" field. — Fix: make this delete case-insensitive like the other sites.
Cost: one edit — no name changes; no ANCHORS entry pins it.

[Q2] MEDIUM `google_sync.py:270` — `if sync_token and synced == 0 and _is_expired_sync_token(exc):` — The thread is lost here. The banners go Step 0, 2, 3, and Step 1 has no banner although it is most of the function. Inside it sit expired-token recovery with a 17-line comment, per-contact savepoints and deferred photo jobs. A stranger changing paging has to hold all of that at once. — Fix: extract the pull as a sibling of `_push_local_changes` and label it Step 1.
Cost: pinned: `docs/specs/2026-07-02-two-way-google-sync.md:345` says "a three-step orchestration inside the existing function"; line 394 of the same spec describes the deferred writes.
Confirms function_sizes `google_sync.py:213`.

[Q1] MEDIUM `routes/contacts.py:173` — `per_page = max(1, min(per_page, 200))` — The ceiling exists as `Config.MAX_CONTACTS_PER_PAGE` (`config.py:218`, read by `settings.py:68`), but it is the literal 200 here and at `models.py:259`. Raising the constant makes the settings page accept a value both clamps silently cut down. — Fix: read the constant at both clamps, keeping the clamps.
Cost: one edit — Searched: `MAX_CONTACTS_PER_PAGE` in docs. `docs/superpowers/plans/2026-07-01-settings-page.md:41` deliberately keeps the clamps, and the fix does too.

[Q4] MEDIUM `routes/contacts.py:191` — `# reuse both here instead of issuing a second COUNT (CL-0017).` — "Both" is false. `list_contacts` returns only rows and total, so the route recomputes `total_pages` (line 192, a copy of `models.py:271`) and re-clamps the page (line 198). A stranger changing the clamp in `models.py` would believe the route follows it, and the page number shown would then disagree with the rows. — Fix: say the route re-derives the page, or return the clamped page from `list_contacts`.
Cost: one edit — comment only, no search owed.

[Q3] MEDIUM `google_sync.py:63` — `def has_credentials(config: dict) -> bool:` — "Credentials" means two files. `has_credentials` checks the app's client secret (`GOOGLE_CREDENTIALS_FILE`), while `_load_credentials`, `_save_credentials` and `revoke_credentials` work on the user's login token (`GOOGLE_TOKEN_FILE`). A stranger would assume `has_credentials` true means the load will find something, or that disconnecting clears it. — Fix: rename the one that checks the client secret.
Cost: pinned: `docs/specs/2026-07-10-standalone-launchers-design.md:213` and `:622` name `has_credentials`.

[Q1] MEDIUM `routes/import_export.py:188` — `flash('That file is too large to import (limit 1 MB).', 'error')` — The limit in this message is by hand, while the real one is `MAX_IMPORT_BYTES` (`config.py:224`), with another copy as the fallback on line 187. Changing the config leaves the message wrong with nothing to prompt the edit. — Fix: build the message from the value in use.
Cost: one edit — Searched: `MAX_IMPORT_BYTES` in docs; `docs/specs/2026-07-01-contact-photos-design.md:198` names it, and the fix does not rename it.

[Q1] MEDIUM `routes/contacts.py:312` — `flash('Photo must be a JPEG, PNG, GIF or WebP under 4 MB.', 'error')` — The same pattern as the last finding, against `photos.MAX_PHOTO_BYTES` (`photos.py:31`). — Fix: build the size from the constant.
Cost: one edit — the constant is read, not renamed. My spec search counted hits for this name across docs without listing them, so I did not read those hits.

[Q4] LOW `google_sync.py:133` — `log.exception('Failed to refresh Google token')` — The docstring (lines 104-106) says only a permanent refusal returns None. This catch-all also returns None, and it covers `_save_credentials` on line 124. A full disk after a good refresh therefore reads as "Not authenticated". — Fix: widen the docstring, or narrow the catch.
Cost: one edit — docstring only, no search owed.

[Q4] LOW `google_sync.py:276` — `# reset can only run before any page has been committed, so it` — `synced` counts imported contacts, not pages, so a committed page of only tombstones leaves it at 0. Under this guard, the `synced = 0` on line 280 is also dead, despite the comment saying it prevents a miscount. — Fix: state what the guard really proves, and drop the dead reset.
Cost: one edit — no name changes.

[Q1] LOW `google_sync.py:566` — `status = getattr(getattr(exc, 'resp', None), 'status', None)` — Reading a People API error is written twice, and differently. `_is_expired_sync_token` (lines 201-210) falls back to `status_code` and decodes the body to text. This one has no fallback and encodes the body to bytes. A fix for one error shape would miss the other. — Fix: one helper returning status and body.
Cost: one edit — Searched: `_is_expired_sync_token`, `_is_write_scope_denied` in DESIGN.md and docs: no hits.

[Q1] LOW `routes/contacts.py:116` — `if contact_type not in ('individual', 'company'):` — `models.VALID_CONTACT_TYPES` exists, but the literal is repeated at `routes/merge.py:102`, `routes/import_export.py:235`, `importer.py:144`, `models.py:211` and `settings.py:59`. Adding a type means finding them all. — Fix: use the constant.
Cost: one edit — Searched: `VALID_CONTACT_TYPES` in docs: no hits. I did not search the specs for the repeated literal, which the fix replaces.

[Q1] LOW `routes/contacts.py:474` — `int_ids = [int(cid) for cid in ids if cid.isdecimal()]` — The comment above records a fix to parsing `selected`. `routes/merge.py:37-41` parses the same field differently with try/`int()`, which accepts `-1` or `1_000`. A change to the rule reaches one site. — Fix: one parser for `selected`.
Cost: one edit — a new helper renames nothing.

[Q2] LOW `routes/merge.py:136` — `def _preserve_extra(key: str, kind: str, chosen: str | None) -> None:` — The reader loses the thread at this nested helper. It changes `customs` and `used` from the enclosing scope, in the middle of an 83-line route that also parses, validates and tracks photos. A stranger reordering steps cannot see that it must run before `merge_contacts` deletes the losers without reading line 132's comment. — Fix: lift it out with explicit arguments and a return value.
Cost: one edit — Searched: `_preserve_extra` in DESIGN.md and docs: no hits. The spec names `merge_apply`, which stays.
Confirms function_sizes `routes/merge.py:89`.

[Q5] LOW `routes/merge.py:51` — `survivor_id = min(c['id'] for c in contacts)` — No comment says why the lowest id survives. A stranger wanting the Google-linked contact to survive cannot tell whether anything depends on this. — Fix: one line giving the reason.
Cost: one edit — comment only, no search owed.

[Q5] LOW `routes/merge.py:102` — `ctype if ctype in ('individual', 'company') else 'individual',` — A bad type is silently turned into `individual` here, and at `routes/import_export.py:235`, while the contact form rejects it. The docstring at `routes/contacts.py:111-112` implies the checks are the same. No comment gives a reason. A stranger would expect merge to refuse a bad type. — Fix: a comment giving the reason, or reject it.
Cost: one edit — comment only, no search owed.

[Q4] LOW `google_auth.py:14` — `# app's sync code. google_sync imports only stdlib + local pure modules at import` — This is false. `phoneutil.py:3` imports `phonenumbers`, and `photos.py:24` imports Pillow, both at import time through `google_sync`. A stranger would wrongly expect the auth script to run without them. — Fix: correct the comment.
Cost: one edit — comment only, no search owed.

[Q4] LOW `routes/sync.py:27` — `# both authorize() and _auth_command reference the same value.` — This is stale. `authorize()` no longer uses it; the only use is line 36 (Searched: `auth_script` in *.py, tests included). — Fix: delete the second half.
Cost: one edit — comment only, no search owed.

[Q4] LOW `routes/contacts.py:375` — `# CL-0066: no region argument -- find_duplicates reads the stored setting,` — The current rule is buried under history. This comment explains an argument that no longer exists. The same happens at lines 226-229 and 314-318, `google_sync.py:281` and `:496`, and `routes/import_export.py:158`. A stranger has to read what used to happen to learn what the rule is now. — Fix: state the rule, and leave the story to the commit history.
Cost: one edit — comment only, no search owed.

[Q3] LOW `google_sync.py:451` — `match = models._BIRTHDAY_RE.match((value or '').strip())` — The underscore says private, but these are shared across modules: `_BIRTHDAY_RE` (also `vcard.py:20`), `_normalize_tags` (`routes/contacts.py`, `routes/merge.py`) and `_safe_ref` (`routes/merge.py:31`). A stranger who searches only the home file would break the other callers. — Fix: drop the underscore on shared names.
Cost: pinned: `docs/specs/2026-07-01-import-export-merge-design.md:229` names `models._BIRTHDAY_RE`; `docs/specs/2026-07-03-tags-labels-design.md:317` names `_normalize_tags`; `docs/specs/2026-07-03-favourite-contacts-design.md:273` names `_safe_ref`.

[tool?: unused module variable] `routes/contacts.py:59` — `log = logging.getLogger(__name__)` — never used in this file; line 319 uses `current_app.logger`.

## Candidates dismissed
- **dup:5bfe3d7912c9:** import lists across the routes. They are declarations with no behaviour to diverge.
- **dup:c2f5be5ad433:** two copies at `google_sync.py:616-621` and `650-655`, matching in behaviour. Nothing beside them records a past fix to both.
- **dup:2a2e8ecfcfdf:** a short fetch-or-404 idiom, also at `routes/contacts.py:434`, `:490` and `:508`. I can name no edit a stranger would get wrong.
- **dup:f5c3427d003c:** the create and update re-render differ on purpose. Only update has a photo, and CL-0079 says so at lines 450-451. `default_type` is not needed on the create re-render, because `contact` is set (`templates/contact_form.html:43`).
- **dup:a87bf7a558c5:** the `models.py` copy and the `routes/contacts.py:122-126` copy share constants, and the comment at lines 120-121 ties the copy to giving a friendly form message.
- **comment_claims census:** Step 3 at `google_sync.py:231`, `:232`, `:282` and `:284` all hold. Step 3 exists at line 354 and in the two-way spec's §5, and `get_dirty_linked` backs the empty-dirty-set claim.
- **function_sizes, not findings:**
  - `_import_vcard_text`, `contact_list`, `import_view`, `merge_preview`, `import_apply`: linear and readable
  - `_apply_photo`: short, with one branch per outcome
  - `_load_credentials`: its problem is the docstring, filed above
  - `revoke_credentials`: over half of it is docstring and logging

## Correctness leads
- `google_sync.py:358` — Step 3 advances `last_synced_at` after per-contact skips and after a scope 403. `models.get_dirty_linked` then no longer sees those edits, so they may never be pushed. The spec (`docs/specs/2026-07-02-two-way-google-sync.md:757`, `:660`) promises a retry next sync. — Searched: `last_synced_at` and the scope-denied message in tests: no test of this case found.
- `google_sync.py:814` — A linked contact with a local "Birthday", "Address" or "Organization" field survives this delete. The insert of lowercase `birthday` should then hit `idx_cf_unique`, roll back and skip that contact on every pull where Google has that field. — Searched: `tests/test_models.py:446` shows "Birthday" being stored as a custom field. I did not run this.
- `google_sync.py:177` — `creds.revoke(...)`: I could not find the library source to confirm this method exists on these credentials. If it does not, line 178 swallows the error and the user sees "Disconnected" with the grant still live. — Searched: `revoke` in tests: only the outage path runs, and the project tree held no copy of the library.
- `google_sync.py:166` — A legacy read-only token, or one whose refresh was refused, makes `_load_credentials` return None. The token is then removed with no revoke attempted and no log line, despite the docstring. — Searched: none.
- `google_sync.py:572` — Any 403 that is not a rate limit becomes "reconnect", including a daily quota refusal or a 403 on the `get` at line 628, which is a read. — Searched: none.
- `routes/merge.py:118` — `merge_preview` emits an uncapped union of custom fields (`templates/merge.html:52`), and rows past `MAX_CUSTOM_FIELDS` are silently dropped here. Extras added by `_preserve_extra` can also exceed the cap at `models.py:786` and fail the merge. — Searched: `cf_count`, `MAX_CUSTOM_FIELDS`.
- `routes/sync.py:93` — On error the route shows no counts, although `google_sync.py:291-293` carefully returns what was committed. — Searched: none.

## Not checked
- **Rate limit:** `workspace_search` was rate-limited late in the run, so I ran those searches with `Grep`, and none went unrun.
- **Partial INV search:** the first `INV-` search stopped at its 200-row cap. I claim only the collisions I read, not that they are the only ones.
- **Partial function-name search:** the search for function names in `*.md` stopped at 60 rows. I re-ran it for the names the Cost lines depend on, except `has_credentials` and `import_apply`, which the capped rows already showed in specs.
- **Unread spec hits:** `MAX_PHOTO_BYTES`, `_normalize_tags` and `_safe_ref` were only counted across docs in the combined search, with no hit listing. The Cost lines cite the tags and favourites spec lines from other searches, so those specs may name them in more places.
- **Not run or read:** I ran nothing, and I read `models.py` and `importer.py` only in slices. I did not open `contacts.db` or `~/.config/contact-list/`.
