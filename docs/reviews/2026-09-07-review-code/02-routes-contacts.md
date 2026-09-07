# Lane 2 — routes-contacts (contacts.py 441, merge.py 161, __init__.py 0)
## Critical (0) / High (0)
## Medium (6)
- [dim 4] merge.py:96-119 — merge write path is a second, DRIFTED copy of the contact-field validation prologue. _validate_form (contacts.py:81-112) applies _EMAIL_RE, _PHONE_RE, phoneutil.format_phone(region) and a 50-field cap; merge_apply applies none. POST /contacts/merge/apply is the one route that can write an email/phone the contact form rejects with 400, and the only write path storing a phone without region normalisation — which is what find_duplicates buckets on.
- [dim 3] merge.py:109,114 — cf_count = int(request.form.get('cf_count', 0)) then range(cf_count). Unbounded loop bound from a request field; cf_count=999999999 in ~20 bytes spins a worker for hours. contacts.py:76's 50-cap has no equivalent here.
- [dim 3] contacts.py:84-98 — NO server-side length limit on name, email, notes or custom-field values. Only caps are browser maxlength attributes (contact_form.html:50,58,89,108) which a direct POST ignores. A single request can store a ~5 MiB name that renders into every list page, the duplicates scan and the CSV export. models._normalize_tags enforces MAX_TAG_LEN server-side — the choke-point pattern exists and these four fields skipped it.
- [dim 16] contacts.py:243-250 — _apply_photo catches only ValueError, but photos.save_photo writes with a bare open() (photos.py:167-169) not wrapped, so disk-full/permission raises OSError as a 500 AFTER create/update already committed. Falsifies its own docstring at :235 ("never blocks saving the contact"). User sees an error page and cannot tell the contact was saved.
- [dim 2] contacts.py:66-75 — a failed custom-field row is not appended to custom_fields, and the error re-render builds form rows FROM custom_fields. The user is shown an error naming a field no longer on the page. The `continue` at :65 drops a half-filled row with no message.
- [dim 2] contacts.py:176-195 — /contacts/duplicates and /contacts/birthdays neither paginate nor bound their result set, against DESIGN 7.2 "all list endpoints paginate". Duplicates is also N+1 plus a phonenumbers parse for every phone-bearing row on one unpaginated render.
## Low / Info
- [dim 5] contacts.py:153 — get_letter_counts full-table scan via the first_letter UDF on every render; cannot use idx_contacts_name.
- [dim 2] contacts.py:368-378 — update error re-render omits photo_ext, so the photo preview AND the "Remove photo" checkbox vanish; a user who ticked Remove loses that intent silently.
- [dim 3] contacts.py:391 — bulk_delete ids unbounded; each costs a get_contact, a delete_contact with its own commit and a full _gc_orphan_tags anti-join.
- [dim 2] merge.py:159 — flash counts the raw submitted list while merge_contacts de-dupes, so a repeated loser_id over-reports.
- [dim 2] [tool: mypy][tool: ruff] contacts.py:55,:81,:230 — untyped form/db params, no return annotations on any route function. Neither tool catches it as configured.
- [dim 2] DOC SIDE — DESIGN 9 omits GET /contacts/birthdays, POST /contacts/bulk-delete, POST /contacts/merge, POST /contacts/merge/apply; 9.1 omits ref and its "default 50" is really the user's Settings value. Hand to review-contract.
## Covered by spec and looks correct
CSRF complete: every state-changing route here is POST-only and app.py:81-86 aborts 403 without a matching hmac.compare_digest token. No route declares methods=['GET','POST']; no GET handler writes. The one GET side effect (photo thumbnail) is specified. No SQL built in these files. _safe_ref held against //host, /\host, CR/LF/U+2028. Path traversal on /contacts/<id>/photo impossible (int-cast basename, DB allow-list ext, send_from_directory). No Markup(, no |safe anywhere under templates/. Tag filtering safe (normalize splits on commas). Pagination clamped in both route and model with identical formulas.
## Open questions
1. Does SQLite elide the three correlated subquery columns in the COUNT wrapper? Needs EXPLAIN QUERY PLAN.
2. When merge_contacts raises ValueError, merge_apply discards the whole merge selection — intended?
## 3 to fix first
1. merge.py:109/114 clamp cf_count. 2. merge.py:96-119 share the validation prologue. 3. contacts.py:243-250 catch OSError.
