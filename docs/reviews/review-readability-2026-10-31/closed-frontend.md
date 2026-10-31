# Closed: frontend lane (CL-0119)

| finding (file:line) | disposition | was -> now, or why, or roadmap id |
|---|---|---|
| contacts.html:171 filter state in link lists (HIGH) | fixed | five hand-written arg lists -> one `list_state` + `list_link` macro; links override only what they change; sort/dir/per_page carried when in the URL; search form carries them as hidden fields. Red run: `test_frontend.py` pagination, letter-link and bulk-ref tests failed (no sort/dir in the links, ref fixed at `/contacts`). |
| duplicates.html:61 avatar rule x7 (HIGH) | fixed | six Jinja copies + JS -> `avatar` macro (A-Z rule) and JS `/^[A-Z]$/` with `?` for blank. Red run: accented-initial test failed (`avatar-É`). |
| duplicates.html:48 group table / name cell x5 (HIGH) | fixed | `dup_group` and `name_cell` macros; render-compare of 11 pages differs only by timestamps and the accented-initial class. Birthdays/Duplicates show no photo because their queries do not select `has_photo` (comment in the macro). |
| app.js:478 custom-field caps (HIGH) | fixed | caps now flow models -> `cf_limits` (context processor) -> `data-max-fields` and the row template's maxlength -> app.js; added `MAX_CF_NAME_LEN` (was literal 64 in four places in models.py/routes). models.py comment rewritten. Test added after the change (no red run). |
| app.js:178 distinct-selection count | fixed | `selectedCount()` used by bar, announcement and delete prompt. Browser check: 6 boxes, 3 contacts, bar said 3. |
| app.js:461 row parts built twice | fixed | one `<template>` row (shared with the saved rows via the `cf_row` macro) and one `decorateRow`. Browser check passed. |
| contacts.html:92 bulk bar x2 | fixed | `bulk_bar` macro. |
| settings.html:112 contact types x4 | fixed | `type_options` macro over `contact_types`; badges loop over it; config.py comment updated. Test: a third type appears in contacts, form and settings. Import map stage covered by existing test. |
| app.js:333 masonry comment | fixed | now says absolute positioning. No red run: nothing observable changes. |
| app.js:245 submit comment | fixed | plain `bulkForm.submit()`; no keydown guard applies to it. |
| app.js:406 early return | fixed | custom fields are their own IIFE with the warning at its top. |
| import.html:6 breadcrumb x6 (LOW) | dismissed | three static lines whose labels and depth differ; a macro taking a list is harder to read than the copies, and no change to them is planned. |
| settings.html:97 sort list (LOW) | queued | CL-0109 (already filed). |
| app.js:543 showModal misuse | fixed | renamed `askConfirm`; the limit notice replaced by disabling Add Field at the cap (title explains). Browser check passed. |
| app.js:336 base.css | fixed | style.css. |
| app.js:575 history comment | fixed | reduced to the constraint. |
| app.js:1 header overstates | fixed | names the features that need JS. |
| contact_form.html:94 2600 | fixed | comment at both sites (MAX_TAGS x MAX_TAG_LEN + separators = 2600, checked). |
| lead: pagination drops sort/dir | fixed | with the filter-state finding. |
| lead: flash auto-removes error lists | fixed | only messages with a dismiss button auto-dismiss. Not timed in a browser. |
| lead: Enter guard blocks links | fixed | guard now only for INPUT targets. Reasoned from DOM behaviour (a prevented keydown cancels link activation); checked only that the handler loads. |
| lead: Clear / untick leave group box | fixed | both reset it. Browser check passed. |
| lead: detail star form lacks ref; birthdays/duplicates links carry no ref; merge Cancel | queued | CL-0120 (needs a route design choice). |
| lead: bulk actions post fixed ref `/contacts` | fixed | ref is the current list URL. Test red first. |
| lead: merge "nothing is lost" | fixed | text now says no email or phone is lost; unpicked name/notes/custom values are dropped (read in merge_apply). |
| lead: "narrow the range" | fixed | no page control sets `days`; text now says add `?days=N`. |
| lead: non-Latin initial has no colour | fixed | `avatar-other`; the base `.avatar` rule sets no background, so the class matters. |

Sweep: searched code, templates, README, DESIGN.md and CLAUDE.md for `showModal`, `avatar_class`, `base.css`, the 64 name cap and the type list. Nothing stale outside dated records (`closed-data.md` still says the models.py comment names app.js; a dated record). DESIGN.md's `{1,64}` stays true. Hand-check list: none exists in the project docs, so not extended.

Gates: `pytest tests/ -q` (549 passed), `ruff check .`, `npx eslint static/`, `node --check`, before/after render compare of 11 pages, one Firefox check on a scratch server (HOME and database in scratch, port 5987, stopped after). Not run: `local-ci.sh`; flash timing, Enter on a link and drag-and-drop were not exercised in the browser.
