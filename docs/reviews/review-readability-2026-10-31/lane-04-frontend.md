## Files read
All files read in full with `Read`:
- `static/app.js` — 663 / 663
- `templates/_macros.html` — 32 / 32
- `templates/about.html` — 19 / 19
- `templates/base.html` — 71 / 71
- `templates/birthdays.html` — 63 / 63
- `templates/contact_detail.html` — 106 / 106
- `templates/contact_form.html` — 130 / 130
- `templates/contacts.html` — 195 / 195
- `templates/duplicates.html` — 170 / 170
- `templates/error.html` — 10 / 10
- `templates/import.html` — 88 / 88
- `templates/merge.html` — 89 / 89
- `templates/server_action.html` — 33 / 33
- `templates/settings.html` — 150 / 150
- `templates/sync.html` — 88 / 88

Cross-references, slices only:
- `static/style.css` 425-441 and 1158-1195
- `models.py` 15-50, 205-290 and 824-830
- `routes/contacts.py` 105-300 and 460-514
- `routes/merge.py` 30-165
- `settings.py` 50-64
- `photos.py` 28-46
- `DESIGN.md` 612-625
- `ROADMAP.md` 1682-1692

## What I started with
- The global `~/.claude/CLAUDE.md`.
- The user's email address, as attached context.
- A session-start note about the Ants MCP verbs.
- The environment block.
- This lane's agent prompt and the lane block, including its one-line paraphrase of the project `CLAUDE.md`.
- No git snapshot, memory index or project `CLAUDE.md` text.

## Summary
These are the web pages of a personal address book, and the small script that makes them nicer to use. The templates draw the contact list, contact details, the add and edit form, duplicates, merging, importing, birthdays, Google sync and settings. The script adds confirmation pop-ups, keyboard shortcuts, bulk selection, the "recently viewed" list, the card layout, draggable custom fields and settings tabs. The pages submit ordinary forms to the server, and the script is meant to be an optional layer on top.

## Findings

[Q1] HIGH `templates/contacts.html:171` — `<a href="{{ url_for('contacts.contact_list', page=page-1, q=search, type=contact_type, letter=letter, tag=active_tags, per_page=per_page) }}">&laquo; Prev</a>` — Each kind of list link keeps its own hand-written set of filters, and the sets differ:
- Alphabet links (44, 49, 58) keep type, q and tag.
- Tag chips (75) keep tag, q, type and letter.
- Sort headers (103, 105) keep q, type, letter, tag, sort and dir.
- Pagination (171, 175) keeps page, q, type, letter, tag and per_page.
- The search form (11-23) keeps q, type and tag.

A stranger adding a new filter will patch some of these and miss others. No comment says which omissions are deliberate. — Fix: build the current filter state once, in the route or a macro, and have each link override only what it changes.
Cost: pinned: `docs/specs/2026-07-03-tags-labels-design.md` line 450 names the chip's `url_for` argument list.
Searched: `*.md` for `contact_list', `, excluding CHANGELOG, ROADMAP and docs/reviews.

[Q1] HIGH `templates/duplicates.html:61` — `{% set avatar_class = 'avatar-' ~ initial if initial.isalpha() else 'avatar-other' %}` — The rule for an avatar's initial and colour exists in seven places, and they disagree:
- Six Jinja copies: `birthdays.html:38-39`, `contact_detail.html:14-15`, `contacts.html:113-114`, `duplicates.html:60-61`, `100-101` and `140-141`.
- One JS copy: `static/app.js:310-311`, which tests `/[A-Z]/`.

An initial like "É" or "Ω" gets `avatar-É` from Jinja, a class with no rule in `style.css` (only A-Z and `-other` exist). JS gives the same name `avatar-other`. For a blank name, Jinja shows `?` and JS shows an empty string. A stranger fixing the colour on one page would leave the others wrong. — Fix: one `avatar` macro in `_macros.html` using the same rule as the JS.
Cost: one edit — Searched: `*.md`, same exclusions, for `avatar_class`, `name-cell` and `_macros`. Specs name `.name-cell` and `_macros.html` but neither blocks adding a macro.
dup:1cb4902f036f (part). Searched: `style.css` for `avatar-` rules, `*.py` for `.isalpha()`.

[Q1] HIGH `templates/duplicates.html:48` — `<table class="mb-md">` — The group table is copied three times (48-76, 88-116, 128-156), and the name cell is a fourth and fifth copy in `birthdays.html:41-46` and `contacts.html:117-128`.
- The three duplicates tables differ only by which column is bolded.
- `contacts.html` passes `ref` to the detail link and shows photos. `birthdays.html:44` and `duplicates.html:67` do neither, with no comment saying why.

A stranger changing a column or the link will patch one table, or won't know whether the gaps are intended. — Fix: one group-table macro taking the bolded column, and one name-cell macro whose differences are explicit parameters.
Cost: one edit — Searched: as the finding above, plus `*.md` for `bulk-status`. No spec names this markup except `.name-cell` in the favourites design, a class the fix keeps.
dup:1cb4902f036f.

[Q1] HIGH `static/app.js:478` — `valInput.maxLength = 500;` — `models.py` (the comment above `MAX_CUSTOM_FIELDS`) says its caps "mirror templates/contact_form.html's maxlength values; change both together". `app.js` is a third copy that the comment doesn't name:
- 64 at `app.js:469`, also in `contact_form.html:106`, `models.py:970` and `models.py:984`.
- 500 at `app.js:478`, also in `contact_form.html:109` and `MAX_CF_VALUE_LEN`.
- 50 at `app.js:409`, also in `MAX_CUSTOM_FIELDS`.

A stranger who follows the comment raises the cap, and newly added rows stay at the old limit. ROADMAP's CL-0092 entry records that JS-built rows are untested because there is no JS runner, so no test would catch this. — Fix: emit the caps as data attributes on `#custom-fields` and read them in `app.js`.
Cost: one edit — Searched: `*.md`, same exclusions, for `MAX_CUSTOM_FIELDS` and `maxlength`. The only `maxlength` hits are the tag cap in the tags design, which this fix doesn't touch.
Searched: `*.py` for `\b64\b`, `MAX_CF` and `MAX_CUSTOM_FIELDS`.

[Q1] MEDIUM `static/app.js:178` — `var count = document.querySelectorAll('.row-select:checked').length;` — The comment at `app.js:233-237` records a fix: one contact can appear as two checkboxes on the duplicates page, so counts must use distinct ids. Only the delete prompt got that fix. The bar and the live announcement (`bulkCount`, `bulkStatus`) still count checkboxes, so the page can say "5 selected" next to "Delete 3". A stranger reading `updateBulkBar` sees nothing about this. — Fix: one distinct-selection count used by both.
Cost: one edit — Searched: `*.md`, same exclusions, for `updateBulkBar` and `bulk-delete-btn`, no hits.

[Q1] MEDIUM `static/app.js:461` — `handle.setAttribute('aria-hidden', 'true');` — Custom-field row parts are built in two places, `createRow` and the enhancement loop: drag handle at 456-462 and 531-535, move buttons at 482-492 and 515-525. The inputs are also copied in `contact_form.html:106-111` and `app.js:464-480`. CL-0092 (comment at `app.js:459-460`, ROADMAP entry) had to patch the template and the JS rows separately. A stranger changing a label or button will likely patch only one route, and which route a row takes depends on whether it was saved. — Fix: one helper adding handle and move buttons for both routes, and one source for the row's inputs.
Cost: one edit — Searched: `*.md`, same exclusions, for `createRow`, `makeDraggable` and `custom-field-row`. The page-construction spec names only the class, which the fix keeps.
dup:39730a46a5e2, dup:fcd83646e278.

[Q1] MEDIUM `templates/contacts.html:92` — `<div class="bulk-bar" id="bulk-bar" hidden>` — The bulk toolbar and its live region are identical in `contacts.html:89-97` and `duplicates.html:27-35`. The same CL-0084 comment sits beside both, which shows the past fix had to patch both. A stranger adding a bulk action would add it to one page and not the other. — Fix: one `bulk_bar` macro in `_macros.html`.
Cost: one edit — Searched: `*.md`, same exclusions, for `bulk-bar`, `bulk-status` and `bulk-delete-btn`. The page-construction spec names `.bulk-bar` only as a class, which the fix keeps.
dup:5caca7a6d281.

[Q1] MEDIUM `templates/settings.html:112` — `<option value="individual" {{ 'selected' if settings.default_type == 'individual' }}>Individual</option>` — The contact types are hand-listed in four templates: `contact_form.html:43-44`, `contacts.html:18-19` (plus the badges at 33-34), `import.html:62-63` and `settings.html:112-113`. `models.py:826` has `VALID_CONTACT_TYPES`, which only `models.py` uses. A stranger adding a type edits the constant and the filter or settings dropdown silently stays short. — Fix: pass the constant to templates and loop over it.
Cost: one edit — Searched: `*.md`, same exclusions, for `individual.*company.*(option|select)`, no hits.
Searched: `*.py` and `*.html` for `VALID_CONTACT_TYPES`.

[Q4] MEDIUM `static/app.js:333` — `// bottom (via CSS-grid 1px row tracks + a per-card row-span) so columns` — This describes a layout that isn't there. The code sets `left`, `top` and `width` on absolutely positioned cards (381-382), and `style.css` (the `tbody.masonry` rules) agrees. A stranger debugging the layout would look for grid tracks and row spans. The "Absolute cards" comment at 386 only partly corrects this. — Fix: reword to say absolute positioning.
Cost: one edit — comment only.

[Q4] MEDIUM `static/app.js:245` — `// Use HTMLFormElement.prototype.submit to bypass the keydown preventDefault` — The reason given is false. `form.submit()` doesn't pass through a keydown handler, and `app.js:100` calls plain `.submit()` with no such concern. A stranger would conclude the Enter-key guard can block programmatic submits and copy this odd call, or be afraid to remove it. — Fix: state the real reason, or use plain `submit()` if there is none.
Cost: one edit — comment only.

[Q4] MEDIUM `static/app.js:406` — `if (!container || !addBtn) {` — This early return silently ends the whole 570-line first IIFE on every page except the contact form, and it has no comment. The reason appears only at 574-582, after the IIFE closes. That comment records this exact mistake being made (CL-0048, with CL-0047 in the tabs banner at 618). A stranger adding a feature at the end of the IIFE would see it work on `/contacts/new` and nowhere else. — Fix: put the warning on this line, or move custom fields into their own IIFE like the two below it.
Cost: one edit — Searched: `*.md`, same exclusions, for `createRow`, `makeDraggable` and `layoutTbody`, no hits. The IIFE has no name to pin.

[Q1] LOW `templates/import.html:6` — `<nav class="breadcrumb" aria-label="Breadcrumb">` — The same breadcrumb frame is copied in `birthdays.html:6-10`, `contact_detail.html:6-10`, `duplicates.html:6-10` and `import.html:6-10`, with longer forms in `contact_form.html:6-16` and `merge.html:6-12`. The copies differ only in their labels, so this isn't a behaviour split. A stranger adding something like `aria-current` must patch six files. — Fix: one breadcrumb macro called inside the existing block.
Cost: one edit — Searched: `*.md`, same exclusions, for `breadcrumb`. The page-construction spec keeps it in `{% block breadcrumb %}`, which the fix also does.
dup:e7a16c20351d.

[Q1] LOW `templates/settings.html:97` — `{% for s in ['name', 'type', 'created', 'updated'] %}` — The sort list is hand-kept in three places, which still match: here, `settings.py:57` and `allowed_sorts` in `models.py`. A new sort added to the model wouldn't appear in Settings, and it would be refused by the settings allow-list. — Fix: one list passed through the settings choices.
Cost: unsure: I did not search specs for the sort list.

[Q3] LOW `static/app.js:543` — `showModal('Maximum ' + MAX_CUSTOM_FIELDS + ' custom fields allowed.');` — `showModal` reads as "show a message", but it always asks a yes/no question with a red Confirm and a Cancel button (`base.html:64-65`). This line uses it as a notice, so the user gets a Confirm button for a limit message. A stranger would copy the misuse. — Fix: rename it to say it asks for confirmation, and give notices their own route.
Cost: one edit — Searched: `*.md`, same exclusions, for `showModal`, no hits.

[Q4] LOW `static/app.js:336` — `// to the plain aligned grid in base.css when JS is absent.` — No `base.css` exists. The rule is in `style.css`, and this comment is the only mention of `base.css` outside CHANGELOG, ROADMAP and docs/reviews. A stranger would search for the file, then recover. — Fix: say `style.css`.
Cost: one edit — comment only.
Searched: tree for `base\.css`, with those three excluded.

[Q4] LOW `static/app.js:575` — `// These used to sit at the end of the custom-fields IIFE above, which` — Nine lines of history bury the one current rule: keep these out of the first IIFE. A stranger reads a past bug report to find it. — Fix: reduce to the constraint and move the story to the commit history.
Cost: one edit — comment only.

[Q4] LOW `static/app.js:1` — `// Progressive enhancement — all handlers degrade gracefully without JS` — This overstates what happens. Without JS, the bulk bar never unhides (`contacts.html:92`), so merge and bulk delete are unreachable. `+ Add Field` and Remove do nothing, and `data-confirm` buttons submit with no confirmation. A stranger adding a JS-only control would assume a fallback exists, or trust that one does. — Fix: say which features need JS.
Cost: one edit — comment only.

[Q5] LOW `templates/contact_form.html:94` — `<input id="tags" name="tags" type="text" maxlength="2600"` — 2600 also appears at `merge.html:80`, with no comment beside either, and appears in no Python file. The reason, a deliberate over-bound of the tag caps, is only in the tags design spec. A stranger changing `MAX_TAGS` or `MAX_TAG_LEN` wouldn't connect them. — Fix: a one-line comment at both sites naming the caps it derives from.
Cost: one edit — comment only.
Searched: `*.py` for `\b2600\b`, `*.md` for `maxlength`.

## Candidates dismissed
- `function_sizes static/app.js:452 createRow (58)` — long but linear element-building. The thread isn't lost, and only its copying is a finding (above).
- `function_sizes static/app.js:412 makeDraggable (39)` — five short listeners, easy to follow.
- `function_sizes static/app.js:352 layoutTbody (38)` — one sequence, well commented.
- `dup:39c94ec099f1` — only the closing tags of a table loop, so no behaviour to share.
- `dup:c77aca42a98a` — two identical forms in `sync.html`, with no comment or ticket showing a shared past fix.
- `comment_claims static/app.js:340 '~0'` — true. `style.css` has `gap: 0.85rem` and `minmax(240px, 1fr)`, matching `CARD_GAP` and `CARD_MIN` as approximations.
- `comment_claims static/app.js:607 '10 promises prefers'` — true. `DESIGN.md` § 10 does promise it.

## Correctness leads
- `templates/contacts.html:171` — Pagination links drop `sort` and `dir`, and the route falls back to the saved default, so clicking Type and then Next loses the chosen sort. Alphabet links, tag chips and the search form drop it too. Sort links and the others drop `per_page`. — Searched: `routes/contacts.py` `contact_list`.
- `static/app.js:8` — Every `.flash` auto-removes after 6 seconds, including the validation error lists at `contact_form.html:23` and `settings.html:9`. Those have no dismiss button and vanish while the user is fixing the form. — Searched: `style.css` for `.flash`.
- `static/app.js:228` — The Enter guard covers everything inside `#bulk-form`, including contact name links and star buttons (`contacts.html:119,125`), so Enter probably can't open a contact from the keyboard. I could not run a browser to confirm. — Searched: none.
- `static/app.js:216-222` — Clear resets `selectAll` and the rows but not `.group-select`. Unticking a row (200) doesn't untick its group box either, so group boxes can stay ticked with nothing selected. — Searched: none.
- `templates/contact_detail.html:29` — The star form carries no `ref`, though the delete form at 95 does. The route then redirects to the detail page without `ref`, so Back loses the filtered list. Adding `ref` as it stands would redirect to the list instead. — Searched: `routes/contacts.py` `toggle_favourite`.
- `templates/birthdays.html:44` — Birthday and duplicate links pass no `ref`, so Back from a contact may not return to the page it came from. I did not read how `list_url` is built. — Searched: none.
- `templates/contacts.html:88` — Bulk actions post a fixed `ref` of `/contacts`, so a filtered list comes back unfiltered. The star forms at 164 use the full path. — Searched: `routes/contacts.py` `bulk_delete`.
- `templates/merge.html:86` — Cancel and the breadcrumb always go to Duplicates, even when the merge began on `/contacts`. — Searched: `routes/merge.py`.
- `templates/merge.html:20` — "so nothing is lost" holds only for email and phone. Unpicked names, notes and custom-field values aren't kept. — Searched: `routes/merge.py` `merge_apply`, read to line 165.
- `templates/birthdays.html:24` — The text says to "narrow the range", but no page control sets `days`. It is only a URL parameter. — Searched: all templates read, `routes/contacts.py` `birthdays`.
- `templates/birthdays.html:43` — A non-Latin initial may get no background colour, because no `avatar-*` rule matches it. I did not open the base `.avatar` rule to see if it sets one. — Searched: `style.css` for `avatar-`.

## Not checked
- I ran no browser or JS, so every behaviour claim comes from reading the code.
- I did not check `routes/import_export.py`, `routes/sync.py` or whether `find_all_duplicates` and `upcoming_birthdays` return `has_photo`. So I can't say whether the missing photos on Birthdays and Duplicates are forced by the data.
- I did not read the tests. I searched them only by file name for selectors, and two test files matched. I did not open them, so a rendered-output test could be affected by the macro fixes. The lane's ANCHORS list none.
- I searched the wider spec set only for the names listed in each Cost line.
- Remaining `_macros.html` claim: I compared inline SVG paths by eye, not by search, for "icons used once stay inline".
