# Two-Way Google Sync — Design (CL-0033)

Status: **Implemented (v2.0).** Passed `/cold-eyes` — 4 loops, 16 independent cold
reviews, zero Critical throughout; findings decayed from real contract bugs
(loop 1: scope-detection tautology, under-specified dirty-defer) → design gaps
(loop 2: dishonest backfill, NULL-prev_sync edge, multi-value ambiguity) →
correctness details (loop 3: last_synced_at gating, RFC3339 parsing) → wording
consistency (loop 4). Implemented test-first in 4 commits; 31 tests added, full
suite 276 green. One external-API assumption (People `get` returns a CONTACT-source
`updateTime` without requesting it) is confirmed at runtime with a safe Google-wins
fallback.
Date: 2026-07-02
Target release: **v2.0** (DESIGN.md §13 already lists v2.0 as "Bidirectional
Google sync").

This spec implements **DESIGN.md §8.3 "Future: Bidirectional Sync (v2+)"**, which
already states the plan: "Requires `contacts` scope (not `contacts.readonly`);
track `updated_at` locally and compare with Google `etag`; last-write-wins with
user confirmation on conflicts." The maintainer's decision (in-session 2026-07-02)
**refines** the conflict rule from "last-write-wins with user confirmation" to
**automatic last-write-wins by timestamp** (newest edit wins, no per-conflict
prompt), with a **post-sync report** of what was pushed and how each conflict was
resolved.

A second maintainer decision (in-session 2026-07-02) folds in an **honest
"last edited by you" timestamp**: today `contacts.updated_at` is bumped by both
user edits **and** the sync pull, so it cannot answer "when did *I* last edit
this?". This spec adds a dedicated local-edit timestamp the sync **never** writes
(this spec's §4), which (a) powers an honest "Last edited" display and (b) makes
the two-way conflict logic simpler and more trustworthy than the previous
draft's compute-at-sync-time trick. It also surfaces these times more widely:
**last-synced in the footer** (every page) and **edited-time in the contact
list** (this spec's §8).

This spec amends the following **DESIGN.md** sections in the same change-set as
the implementation:

- **§1** — already claims "bidirectional Google Contacts integration"; no wording
  change needed, but this feature is what makes it true.
- **§4 (Data Model)** — adds a **new `### 4.x contact_edits` Table** subsection
  (one row per contact, `edited_at`); no new column on `contacts`. It reuses the
  **companion-table pattern** of the CL-0026 `contact_photos` table
  (`migrations/005_photos.sql`) — *pattern only*, not its columns: `contact_edits`
  carries `edited_at`, not `contact_photos`'s `updated_at`. (DESIGN §4 currently
  documents only `contacts`/`custom_fields`/`sync_state`; `contact_photos` (005) and
  `import_profiles` (004) were added by later migrations without §4.x subsections —
  a pre-existing DESIGN drift, independent of this feature. This change adds the
  `contact_edits` subsection; documenting the two already-shipped tables is optional
  cleanup, not required by this spec.)
- **§4.4 (Schema Conventions)** — that section states "New tables must include
  `created_at` and `updated_at`." **No existing table meets it** (verifiable
  directly in `migrations/`: `custom_fields` has only `created_at`; `contact_photos`
  and `import_profiles` have only `updated_at`; `sync_state` has neither) — so the
  convention is already aspirational, **regardless of whether the two undocumented
  tables above ever get §4.x subsections**. `contact_edits` deliberately carries
  **only** `edited_at`. Amend §4.4 to permit a table whose sole purpose is one
  domain timestamp to name that column instead of the generic pair. (This amendment
  stands on its own — it does not depend on the optional §4.x documentation above.)
- **§6.2 (Security → Google OAuth → Scopes row)** — "Request only
  …`contacts.readonly`… Upgrade to `.contacts` only if write-sync is added." This
  spec **is** that upgrade; the scope becomes
  `https://www.googleapis.com/auth/contacts`. (Security is §6, not §5 — §5 is
  Architecture.)
- **§8.2 (Sync Strategy)** — replace the "Import direction (v1): Google → Local
  only" bullet with "**Sync direction (v2.0): bidirectional** — pull all changed
  Google contacts; push local-only contacts (create) and locally-edited linked
  contacts (update); deletions are **not** pushed (this spec's §2)"; and replace
  the "Conflict resolution: … Local-only contacts are never pushed" text with
  "**Conflict resolution: automatic last-write-wins by `updateTime` (this spec's
  §7); local-only contacts ARE pushed as new Google contacts.**"
- **§8.3** — this spec realises it; its two mechanism bullets are refined: "Track
  `updated_at` locally and compare with Google `etag`" becomes "track a dedicated
  `edited_at` (this spec's §4) and compare `updateTime` timestamps; the `etag` is
  the write-time precondition backstop, not the conflict signal", and "Last-write-
  wins **with user confirmation**" becomes "**automatic** last-write-wins by
  timestamp, with a post-sync report" (no per-conflict prompt).
- **§9 (Routes)** — `/sync/start` changes from "Trigger Google import" to "Trigger
  Google sync (import **and** export)"; no new route (this spec's §11).
- **§13 (Versioning)** — the v2.0 row reads "Bidirectional Google sync, REST JSON
  API". **Split it**: edit the v2.0 row to read just "Bidirectional Google sync"
  (what this spec ships) and **move "REST JSON API" to a new `v2.2` row** (deferred,
  this spec's §15), so the v2.0 line does not overstate what v2.0 delivers.

**No new pip dependency.** All People API write calls use the existing
`google-api-python-client` service object. Direct runtime deps stay at **6**
(Dependency Budget, DESIGN.md §3). **One schema migration** is added — a
`contact_edits` companion table (this spec's §4) — following the idempotent
`CREATE TABLE IF NOT EXISTS` pattern the runner requires.

Sections: [1 Overview](#1-overview) · [2 Scope & non-goals](#2-scope--non-goals) ·
[3 OAuth scope upgrade](#3-oauth-scope-upgrade--re-consent) ·
[4 Local-edit timestamp](#4-local-edit-timestamp-honest-last-edited) ·
[5 Sync algorithm](#5-sync-algorithm) ·
[6 Field mapping & multi-value preservation](#6-field-mapping--multi-value-preservation) ·
[7 Conflict resolution](#7-conflict-resolution-timestamp-lww) ·
[8 UI: report, footer & list times](#8-ui-post-sync-report-footer--list-times) ·
[9 Error handling & idempotency](#9-error-handling--idempotency) ·
[10 Security](#10-security) · [11 Routes](#11-routes) ·
[12 Files & size budget](#12-files--size-budget) · [13 Testing](#13-testing) ·
[14 Invariants](#14-invariants) · [15 Out of scope](#15-out-of-scope-v20).

## 1. Overview

Today `google_sync.sync_contacts` is **pull-only**: it reads changed contacts
from Google (delta via `syncToken`) and upserts them locally. This feature adds a
**push** phase to the same user-triggered "Sync now" action so that, after the
pull, the app sends local changes back to Google:

- **New local contacts** (no `google_id`) are **created** on Google.
- **Locally-edited contacts** that are linked to Google are **updated** on Google.
- **Conflicts** (the same contact changed on both sides since the last sync) are
  resolved **automatically: the newest edit wins**, compared by timestamp.

Deletions are **not** pushed in v2.0 (this spec's §2, §15). Single-user, localhost,
user-triggered, no background threads (DESIGN.md §7.2 unchanged).

> **Pre-implementation gate (one external-API assumption).** The conflict logic
> (§7) reads each contact's Google-side last-edit time from
> `metadata.sources[type==CONTACT].updateTime` on a `people().get()` — a field the
> People API is expected to return *without* it being listed in `personFields`.
> This is the single dependency not verifiable from this repo. Confirm it on the
> live API before trusting §7's last-write-wins; if the field is ever absent, §7's
> defined fallback is **Google-wins** (never overwrite Google when we can't prove
> our edit is newer), so the feature degrades safely rather than incorrectly.

## 2. Scope & non-goals

**In scope (v2.0):**

1. Push-create every local-only contact (`google_id IS NULL`) to Google.
2. Push-update every Google-linked contact edited locally since the last sync.
3. Automatic timestamp last-write-wins on conflicts, with a post-sync report.
4. OAuth scope upgrade `contacts.readonly` → `contacts`, with re-consent handling.

**Explicit non-goals (kept out to bound risk — §15):**

- **No deletions pushed to Google.** Deleting a linked contact locally leaves it
  on Google. Because sync is delta (`syncToken`), a deleted-locally contact does
  **not** silently reappear on the next normal sync (Google only returns *changed*
  contacts); it can reappear only on a **full re-sync** (expired token). This
  trade-off was the maintainer's choice ("edits + new contacts", not "everything
  incl. deletions") and is stated to the user in the §8 report and the README.
  **This narrows CL-0033's original ROADMAP scope**, whose body/Layman line
  promised pushing "deletions" and listed `deleteContact`; the ROADMAP item is
  re-scoped to v2.0 = edits + creates (deletions tracked as future work, §15) when
  this spec lands, so the roadmap and spec do not contradict.
- **No per-contact "don't sync" opt-out.** The chosen policy is "new contacts
  become Google contacts", so **all** local-only contacts are pushed — including
  ones created long before this feature shipped. The first two-way sync therefore
  performs a **one-time bulk create** of every local-only contact. This is the
  intended behaviour; a future opt-out flag is §15.
- **No multi-value editing.** The app models one email and one phone per contact;
  it never *edits* a contact's *secondary* emails/phones on Google, and §6
  guarantees it never *deletes* them either.

## 3. OAuth scope upgrade & re-consent

`SCOPES` changes from `['https://www.googleapis.com/auth/contacts.readonly']` to
`['https://www.googleapis.com/auth/contacts']` (read-write; this single scope
covers reading too, so `contacts.readonly` is dropped, not added-to). The constant
is currently **duplicated** as two independent literals (`google_auth.py` module
top and `google_sync.py` module top). **Eliminate the duplication (mandatory, not
optional):** define `SCOPES` **once** in `google_sync.py` and have `google_auth.py`
do `from google_sync import SCOPES`. Then there is a single literal and INV-5 holds
by construction — no two values *can* diverge. (`google_auth.py` runs as a
subprocess from the same package dir, so the import resolves; if that import is
undesirable, put `SCOPES` in a tiny shared module both import. Do **not** leave two
hand-maintained literals.)

**Re-consent is mandatory and must be detected, not assumed.** An existing
`token.json` was minted for the read-only scope and cannot authorise writes. The
current `_load_credentials` (`google_sync.py`) does **no** scope check at all, so
this guard is **net-new code**, not a tweak to an existing check.

- **One shared file-scope probe helper.** Add a single private helper
  `_token_has_write_scope(config) -> bool`: the token file exists **and** a probe of
  its **own recorded scopes** includes the write scope. Both `_load_credentials` and
  `needs_reconsent` call this one helper (do **not** route detection through
  `_load_credentials`, which returns `None` for *both* "no token" and "legacy token"
  and so cannot tell them apart). The probe:
  `probe = Credentials.from_authorized_user_file(path)` (scopes **omitted** →
  `probe.scopes` reflects the token file's stored scopes; verified against the
  library) then `probe.has_scopes(SCOPES)`. A token file lacking a `scopes` key at
  all (`probe.scopes is None`) → `has_scopes` False → treated as needs-reconsent
  (same path as legacy). **The trap this avoids:** `has_scopes` inspects
  `creds.scopes`, and `Credentials.from_authorized_user_file(path, SCOPES)` sets
  `creds.scopes` to the **argument** — so building creds with the new write `SCOPES`
  and calling `has_scopes(SCOPES)` returns **True tautologically**, masking a legacy
  token (confirmed against the installed library). The probe must therefore omit the
  scopes arg. `has_scopes` and the no-scopes-arg file-read behaviour are verified on
  the installed 2.55.x and are stable in `google-auth` 2.x (the pin is `>=2.0,<3.0`;
  do not hard-depend on a patch version).
- **How the two auth calls use the probe.** `_load_credentials`: if a token file
  exists but `not _token_has_write_scope(config)`, return `None` (unusable — same as
  no token) so nothing attempts a write that 403s; otherwise load with `SCOPES` as
  today (that object keeps `SCOPES`, which refresh needs — **do not** strip them).
  `is_authenticated(config)` is unchanged in shape (`creds = _load_credentials(...)`;
  `creds is not None and creds.valid`) and so is False for a legacy token *by
  construction*. `needs_reconsent(config) -> bool` returns `token-file-exists AND
  NOT _token_has_write_scope(config)` — True only for a legacy/insufficient token,
  False for no-token — so the `/sync` route can render "Reconnect to Google (new
  permission needed)" for a legacy token vs the plain "authorise" prompt when no
  token exists.
- **Re-auth path:** the `/sync` template gains a **Reconnect button** (new UI) that
  POSTs to the existing `/sync/authorize` route (`routes/sync.py`; the route is
  unchanged), which runs the **standalone `google_auth.py` script as a subprocess**.
  Its `InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)` picks up the
  new scope automatically once `google_auth.py`'s `SCOPES` is bumped, so re-running
  mints a read-write `token.json`. No other change to that script.

**Downgrade note:** requesting `contacts` when the user only wants import is a
real permission increase. It is unavoidable for write-sync and is disclosed on the
`/sync` page and in the README (the app still only ever pushes the fields it
manages — §6 — and never deletes — §2).

## 4. Local-edit timestamp (honest "last edited")

**Requirement:** the push phase must know which local contacts were edited by the
**user** since the last sync — and the UI must show an honest "you last edited
this" time. `contacts.updated_at` cannot serve either: it is bumped by **both**
user edits (`create_contact`/`_write_contact`) **and** the sync pull
(`_upsert_person`), so it conflates "you changed it" with "a sync refreshed it".

**Design: a dedicated `edited_at` the sync never writes.** Store the last
*user* edit in a companion table — **not** a new column on `contacts`, because the
migration runner requires every migration to be idempotent and SQLite has no `ADD
COLUMN IF NOT EXISTS` (the exact rationale that shaped `contact_photos`, CL-0026).

`migrations/006_contact_edits.sql`:

```sql
CREATE TABLE IF NOT EXISTS contact_edits (
    contact_id INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    edited_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

`006` is the next free migration number — the full existing set is `001_initial`,
`002_add_indexes`, `003_settings` (a `settings` table), `004_import_profiles`,
`005_photos`, with `005` the highest (re-verify at implementation time and renumber
if an earlier-unreleased migration lands first; §12's `006` filename inherits this
caveat). `ON DELETE CASCADE` (with the `PRAGMA foreign_keys = ON` that `db.py
get_db` already sets — and the migration runner `init_db` shares `get_db`, so FKs
are ON during migrations too) auto-removes the row on contact delete. The migration is **just** the `CREATE TABLE IF NOT EXISTS`,
which is trivially idempotent under the runner's crash window (`db.py init_db` —
`executescript` self-commits before the `schema_version` INSERT, so a re-run must
be a no-op).

**No backfill — deliberately.** Existing contacts get **no** `contact_edits` row at
migration time; `edited_at` stays absent until the user genuinely edits the contact
after upgrade. Backfilling from `updated_at` was rejected because `updated_at` is
contaminated by the pull (§ intro): a synced-but-never-user-edited contact would be
handed a fake "edited" time (the last sync's time), reintroducing exactly the
dishonesty this feature removes. So a never-user-edited contact — imported or
pre-existing — honestly has **no** last-edit time (the display shows nothing, §8.2;
dirty detection never flags it, below). The cost is only that a *pre-upgrade* user
edit to a Google-linked contact isn't retroactively pushed on the first two-way
sync; the user re-touching it makes it dirty. Accepted.

**Write rule (the one invariant that makes it honest, INV-1):** `edited_at` is
upserted to `now` by **exactly** the user-facing writers in `models.py`, via a
single private helper `_mark_edited(db, contact_id)` called inside the caller's
existing `with db:` transaction (no extra commit):

(Note `create_contact` and `import_contact`'s create branch each do a **direct**
`INSERT INTO contacts`, not via `_write_contact`, so all three writers need their
own `_mark_edited` call — putting it only in `_write_contact` would miss creates.)

- `create_contact` — always (a new user-entered contact).
- `_write_contact` — always; this covers `update_contact` **and** `merge_contacts`
  (both compose it). `merge_contacts` marks **only the survivor** (its single
  `_write_contact(survivor_id, …)` call); the losers are deleted and their
  `contact_edits` rows vanish by `ON DELETE CASCADE` — correct, the survivor is the
  edited row.
- `import_contact` — it has **two** branches (verified against `models.py`); mark
  edited only where data actually changes, **not** on a no-op match:
  - **create branch** (`match_id is None`, always `INSERT`) → mark.
  - **additive-update branch** — mark **iff** either sub-condition fired: the core
    `UPDATE` ran (`(new_email, new_phone, new_notes) != current`) **or** custom
    fields were added (`to_add` non-empty). Both guards must be tested (the two are
    independent in the code); a pure no-op match (nothing filled, nothing added)
    must **not** move `edited_at` (it wasn't an edit).

`edited_at` is **never** written by `google_sync._upsert_person` (the pull). Note
`_upsert_person` *does* call one model helper — `set_contact_photo` (via
`_store_person_photo`) — but that writes `contact_photos`, not `contact_edits`, and
never calls `_mark_edited`; so the pull leaves `edited_at` untouched (INV-1 holds).
Combined with the no-backfill decision above, a contact the user has never edited —
imported or pre-existing — has **no** `contact_edits` row (`edited_at` is NULL),
correctly "not edited by you", for **all** contacts (not just post-migration ones).

**Dirty detection for push** then reads this clean signal (no snapshot-ordering
subtlety, because `edited_at` is immune to the pull):

```sql
SELECT last_synced_at FROM sync_state WHERE id = 1;          -- prev_sync (may be NULL)

-- linked contacts the USER edited since prev_sync -> candidates for push-update.
-- A NULL prev_sync (never synced) yields ZERO dirty_linked: with nothing pulled
-- there are no linked contacts, and the first sync only creates local-only rows
-- (matching the §5 Step 0 prose). The INNER JOIN also drops NULL-edited_at rows.
-- The `:prev_sync IS NOT NULL` guard is the canonical source of the "dirty_linked
-- is empty on a never-synced DB" rule that §5 Step 0 and §7 both rely on; it is
-- belt-and-braces over SQLite's 3VL (`x > NULL` is already NULL, not TRUE).
SELECT c.id, c.google_id
FROM contacts c JOIN contact_edits e ON e.contact_id = c.id
WHERE c.google_id IS NOT NULL
  AND :prev_sync IS NOT NULL AND e.edited_at > :prev_sync;    -- dirty_linked

-- every local-only contact -> candidates for push-create (all of them, §2)
SELECT id FROM contacts WHERE google_id IS NULL;              -- local_only
```

`dirty_linked` rows carry **both keys** because its two consumers key differently:
Step-2 push works from the local `id`, while Step-1's pull-deferral must match the
pull's own `google_id` (the pull knows a person only by its `resourceName` /
`google_id`, never the local `id`). Step 0 therefore also materialises a
**`dirty_google_ids: frozenset[str]`** (the `google_id`s of `dirty_linked`, an
immutable snapshot) for the deferral (§5 Step 1). `NULL prev_sync` (never synced) means the first-ever sync
only *creates* local-only contacts and imports; it does not push-update (nothing
has diverged from a Google baseline yet), which is correct. Data-access helpers to
fetch these sets and to read/format a contact's `edited_at` live in `models.py`
(§12).

## 5. Sync algorithm

`sync_contacts(config, db, region)` becomes a three-step orchestration inside the
existing function (one DB connection, one user action):

**Step 0 — snapshot (§4).** Read `prev_sync` (the current `last_synced_at`) and
compute the `dirty_linked` + `local_only` id sets **now**, before Step 1 or Step 3
runs. `prev_sync` is captured here **specifically because Step 3 overwrites
`last_synced_at`** — and the dirty sets are computed once here and **never
recomputed** after Step 3 advances the baseline (recomputing post-Step-3 would find
zero dirty rows and skip the pushes). On the first-ever sync `prev_sync` is NULL, so
`dirty_linked` is empty (§4 SQL) — the guarantee §4/§7 rely on holds precisely
because this snapshot precedes the Step-3 write.

**Step 1 — Pull (existing loop, one change).** `_upsert_person` currently has the
signature `_upsert_person(db, person, region, config)` and matches an existing row
by `person['resourceName']` (= `google_id`). Give it one new parameter —
`_upsert_person(db, person, region, config, skip_google_ids: frozenset[str] = frozenset())`
— and, at its top, `if person.get('resourceName') in skip_google_ids: return
False` (deferred, treated like the existing no-op returns). `sync_contacts` passes
`dirty_google_ids` (from Step 0) as `skip_google_ids`. Effect: a pulled person that
matches a locally-edited contact is **not overwritten** — the local edit survives
for Step 2 to resolve — while a brand-new Google contact, or a linked-but-not-dirty
one, is imported exactly as today. Keying is by `google_id` on both sides (that is
why Step 0 built `dirty_google_ids`, not just the local-`id` set). The per-contact
`SAVEPOINT` isolation and per-page commit are unchanged. All existing
`_upsert_person(...)` call-sites (including `tests/test_hardening.py`) keep working
because `skip_google_ids` defaults to empty.

**Step 2 — Push.** Runs **after** Step 1's final `db.commit()` (the pull commits
each page and the sync-token/`last_synced_at` write is deferred to Step 3), so the
push never interleaves with an uncommitted pull page. Each pushed contact is its
own committed unit, isolated in its own `try/except` — one failure is logged and
skipped, never aborting the run. (This per-contact commit is the isolation
mechanism; it is **not** a strict copy of the pull's `SAVEPOINT` model. (This
spec originally flagged that `_upsert_person → set_contact_photo` did a
`db.commit()` mid-savepoint as an out-of-scope "code-side question". That
turned out to be a live bug — the commit destroyed the savepoint, so
`RELEASE SAVEPOINT person` threw `no such savepoint` and `/sync/start` 500'd
for any pulled contact with a photo. **Resolved in CL-0045**: the photo
helpers no longer commit; the caller owns the commit.)
For each id captured in Step 0:

- **`local_only` → `createContact`.** Build a full person body from the local row
  (§6), call `people().createContact(body=…)`, then store the returned
  `resourceName` into `contacts.google_id` and the returned `etag` into
  `contacts.etag`, and **`db.commit()` immediately** (per-contact, mirroring the
  pull's per-page commit). Committing the link before moving on is what makes INV-6
  hold: a mid-run crash leaves already-created contacts linked, so a re-run never
  double-creates them (People API `createContact` has no client idempotency key, so
  "persist the link at once" is the guard).
- **`dirty_linked` → `updateContact` with conflict check (§7).** Read the live
  Google contact first — `people().get(resourceName=…, personFields=<managed>)` —
  to obtain (a) its current field values for multi-value preservation (§6), (b) a
  **fresh etag**, and (c) its last-edit time. That time is
  `metadata.sources[type==CONTACT].updateTime`, which the People API returns
  **automatically** on a `get` — `metadata` is **not** a `personFields` value (do
  not add it there; listing it would 400). Then either apply Google→local (Google
  won), or overlay local values and `people().updateContact(resourceName,
  updatePersonFields=<managed>, body=person_with_fresh_etag)` (local won), and
  `db.commit()` after a successful write. **Implementation-time check:** confirm on
  the live API that `get` returns a `CONTACT`-source `updateTime` without requesting
  it (unverifiable from the repo alone); §7's whole comparison rests on it.

**Step 3 — finalise.** Advance `last_synced_at = strftime(now)`, and write the new
`syncToken` when one was returned. **`last_synced_at` must advance UNCONDITIONALLY
on a clean finish** — decouple it from the sync-token write. Today the code writes
`sync_state` **only** inside `if new_sync_token:` (`google_sync.py`), so a sync that
returns no new token would leave `last_synced_at` stale; that must change, or the
next run's `prev_sync` is old and it re-pushes edits it already pushed. So: always
update `last_synced_at` on success; update `sync_token` too when present. Advancing
`last_synced_at` re-baselines dirtiness: a contact is dirty only when `edited_at >
prev_sync`, and the next sync's `prev_sync` becomes this `now`, so nothing this run
touched counts as dirty next time.

**Ordering rationale:** pull-before-push means Step 1 refreshes local data +
etags for non-conflicting contacts, and Step 2's per-contact `get` always reads
the freshest Google state right before writing, minimising etag races. **Self-echo
is safe:** a contact this run pushes to Google is recorded by Google as changed,
so the *next* sync's delta returns it with a newer `updateTime` — but because the
push never touched its `edited_at`, it is **not** dirty, so it is imported cleanly
as an ordinary Google change (no false self-conflict). This is a load-bearing
consequence of `edited_at` being pull-immune (§4).

## 6. Field mapping & multi-value preservation

**Managed fields** (the only ones this app reads or writes) and their People API
`personFields`:

| Local | Google `personField` | Cardinality on Google |
|-------|----------------------|-----------------------|
| `name` | `names` | list (we manage the primary) |
| `email` | `emailAddresses` | **list** (we manage one) |
| `phone` | `phoneNumbers` | **list** (we manage one) |
| `notes` | `biographies` | list (single in practice) |
| custom `birthday` | `birthdays` | list (single in practice) |
| custom `address` | `addresses` | list (single in practice) |
| custom `organization` | `organizations` | list (single in practice) |

**`organizations` source (disambiguated).** On import the app either sets
`type='company'` (an org contact whose `name` *is* the org) **or** stores an
`organization` custom field (an individual's employer) — see `_upsert_person`'s
classifier. For the **push**, `organizations[0].name` is fed **only** from the
`organization` custom field when present. A `type='company'` contact is **not**
synthesised into an `organizations` entry — its org name already lives in `name` →
`names` (as Google itself renders company contacts), so pushing it again as an
organization would duplicate it. So `organizations` is in the managed set for the
custom-field case only; a contact with no `organization` custom field omits the
`organizations` personField entirely from its `updatePersonFields`.

`updatePersonFields` for an **update** lists **only** the fields being written,
and the fields written are only those the app manages. It **never** includes a
personField the app does not manage, so Google-side data outside this set (photos
on the Google side, relations, events, memberships, etc.) is untouched.

**Multi-value preservation — the data-loss guard (INV-2).** The app stores only
one email and one phone, but a Google contact may have several. Because
`updateContact` **replaces** the entire value list for each `updatePersonFields`
entry, a naive push of `emailAddresses=[our one email]` would **delete the
contact's other emails on Google**. To prevent that, the update path does
**read-modify-write** using the Step-2 `get` result:

- **`emailAddresses` / `phoneNumbers`:** start from the **live Google list** and
  replace the **first entry (index 0)** in place — set its `value` to ours, keeping
  its other keys (`type`, `metadata`) — then keep entries `[1:]` unchanged; if the
  list is empty, push a single new entry with our value. **Position-based, not
  value-matching:** the app imports `…[0].value` (`_upsert_person` reads
  `phoneNumbers[0]`/`emailAddresses[0]`) and re-formats the phone via
  `phoneutil.format_phone`, so our stored value need not equal Google's raw stored
  string — a value-equality match could silently miss and clobber the wrong entry.
  Replacing index 0 is deterministic and mirrors what we imported. Accepted
  limitation: if Google reordered the list so a *different* number is now `[0]`, we
  update that one; still no entry is ever dropped (INV-2 holds). Never drop an entry
  the app didn't add.
- **`names` / `biographies` / `birthdays` / `addresses` / `organizations`:**
  single-valued in this app's model and in normal use; replace index 0 in place and
  preserve any additional entries the same way.

**`createContact`** has no existing values to preserve, so it sends our managed
fields directly (still only managed fields — never fabricates data). A birthday is
emitted as a People API `birthdays[].date` `{year?, month, day}`, reversing the
import parse (`YYYY-MM-DD`/`MM-DD`, CL-0038); a value that doesn't parse is simply
omitted, never sent malformed.

A helper `_person_body_for_push(local_row, custom_fields, existing_person|None)`
centralises this mapping so create (existing=None) and update (existing=live get)
share one implementation.

## 7. Conflict resolution (timestamp LWW)

A conflict is: a `dirty_linked` contact whose Google copy **also** changed since
`prev_sync`. Detected in Step 2 via the per-contact `get`:

```
google_updated = parse(metadata.sources[type==CONTACT].updateTime)   # datetime
local_edited   = parse(contact_edits.edited_at)                       # datetime
prev_sync_dt   = parse(prev_sync)                                     # datetime
google_changed_since_sync = google_updated > prev_sync_dt
```

**Compare parsed datetimes, not strings.** All three values are parsed to
timezone-aware UTC `datetime`s **before** any comparison — do **not** string-compare
them the way §4's dirty-detection SQL compares `edited_at > :prev_sync` (that SQL
compare is safe only because both operands are the app's own second-precision
`'%Y-%m-%dT%H:%M:%SZ'` strings). Google's `updateTime` is RFC3339 with **fractional
seconds** and possibly a numeric offset (e.g. `2026-07-01T12:00:00.123456Z` or
`…+00:00`); a naive string compare against the app's second-precision `…Z` local
timestamp would mis-order. Parse with an RFC3339-tolerant parser (e.g.
`datetime.fromisoformat` after normalising a trailing `Z` to `+00:00`, or
`dateutil`), normalise to UTC, then compare.

`prev_sync` is never NULL here: a `dirty_linked` contact requires a non-NULL
`prev_sync` (§4 SQL), so the comparison always has both operands. The local side
uses the honest **`edited_at`** (§4), not `updated_at` — the "newest wins"
comparison must weigh *your* last edit against Google's last edit, and `updated_at`
is contaminated by the pull. A `dirty_linked` contact always has an `edited_at`
(that is what made it dirty), so `local_edited` is never NULL either.

**Missing `updateTime` fallback.** If the `get` response has no `CONTACT`-source
`updateTime` (should not happen, but the field is not contractually guaranteed),
resolve **Google-wins** — do **not** push (never overwrite Google when we cannot
prove our edit is newer). Because this means a locally-edited contact is **not
pushed**, it is counted separately in `SyncResult.push_no_time` (§8.1) and surfaced
in the report ("N edits couldn't be pushed — Google's edit time was unavailable"),
**not** silently folded into the conflict counts — so a systematic absence of
`updateTime` (which would quietly turn push-updates into a no-op) is visible, not
hidden. Creates are unaffected (they don't read `updateTime`).

- **Not `google_changed_since_sync`** → no conflict → push local (overlay +
  `updateContact`).
- **Conflict** (both changed) → **newest wins** (tie → Google, the safe default):
  - `local_edited > google_updated` → **Local wins**: overlay + `updateContact`.
    Reported as "kept your newer version".
  - else (Google strictly newer, **or equal**) → **Google wins**: apply
    Google→local (overwrite the local row via the same mapping the pull uses), do
    **not** push. Reported as "kept Google's newer version".

Both sides are UTC (SQLite `strftime` writes `…Z`; People API `updateTime` is
RFC3339 UTC), compared as parsed datetimes (the parse note above). **Clock-skew
caveat (accepted):** the comparison trusts the local machine clock vs Google's
server clock; for a single-user localhost tool with human-paced edits (edits
seconds-to-minutes apart, not milliseconds) skew is immaterial. Noted, not
mitigated. Ties resolve **Google-wins** (the safe default — never overwrite Google
on a tie).

**etag backstop (INV-3):** even if the timestamp logic mis-picks "local wins",
`updateContact` carries the **fresh etag from the Step-2 `get`**. If Google changed
again between the `get` and the `update` (a race window of milliseconds), the API
rejects the write with an etag/precondition error; the contact is then **skipped
and reported as a conflict-to-retry** (next sync re-reads and re-resolves). No
silent overwrite of a newer Google state can occur.

## 8. UI: post-sync report, footer & list times

### 8.1 Post-sync report

`sync_contacts` returns a structured result instead of the current `(int, str |
None)`:

```python
@dataclass
class SyncResult:
    pulled: int          # contacts imported/updated from Google (as today's count)
    created: int         # local-only contacts created on Google
    updated: int         # linked contacts updated on Google
    conflicts_google: int  # conflicts resolved Google-wins
    conflicts_local: int   # conflicts resolved local-wins
    skipped: int         # per-contact push failures (logged, not fatal)
    push_no_time: int    # linked contacts whose Google updateTime was absent (§7 fallback)
    error: str | None    # fatal error (unchanged semantics from today)
```

The `/sync` route (`start_sync`) reads the result by **attribute access**
(`result.pulled`, `result.error`, …) — a plain `@dataclass` is **not**
tuple-unpackable, so the current `count, error = sync_contacts(...)` becomes
`result = sync_contacts(...)` then attribute reads. It flashes a one-line summary
("Synced: 12 imported, 3 created on Google, 2 updated, 1 conflict kept your
version.") and the page can list the skipped/conflict contacts by name for
transparency. This replaces the current bare "N synced" message. Tests that call
`sync_contacts` must be updated for the new return type in the same commit (§13).

### 8.2 Honest "Last edited" on the contact detail page

`contact_detail.html` currently shows `Created:` and, when it differs, `Updated:`
(`contact.updated_at`). The ambiguous `Updated:` line — which moves on a sync — is
**replaced** by an honest **`Last edited: {edited_at|friendly_date}`** driven by
`contact_edits.edited_at`. The template renders it only when `edited_at` is
**non-NULL** (a `contact_edits` row exists) **and** `edited_at != created_at` — so a
never-user-edited contact (no row → NULL) shows just `Created:`. The NULL guard is
new: the old `updated_at` path never hit NULL (that column is `NOT NULL`), but
`edited_at` is absent for unedited contacts. `friendly_date(None)` returns `''`
(it guards `if not value: return ''`, `app.py` — it does **not** raise), so without
the `{% if edited_at and edited_at != created_at %}` guard the template would render
a bare `Last edited:` label with an empty value; the guard suppresses the label
entirely for never-edited (and unchanged-since-create) contacts.

The detail route reads the value via a small `get_edited_at(db, contact_id)` helper
(one indexed PK lookup) and passes it in, rather than widening `get_contact` with a
correlated-subquery column as the **list** does (§8.4). The two mechanisms differ on
purpose: the list query already fans a scalar column across every row cheaply, while
the detail route has a single known id where one direct lookup is simpler than
threading a new column through `get_contact`'s shared row shape. `friendly_date`
(registered `app.py`) formats it. (`updated_at` stays in the DB — still written by
the pull — it is just no longer the *displayed* "edited" signal.)

### 8.3 Last-synced in the footer (every page)

`base.html`'s footer already renders a global `contact_count` from the
`_inject_globals` context processor (`app.py`). Add `last_synced` to that same
processor — one cheap `SELECT last_synced_at FROM sync_state WHERE id = 1` per
request (single indexed row; memoise on `g`) — and render **`Last synced:
{last_synced|friendly_date}`** in the footer (or "Never" when NULL/absent). Two
notes: (1) unlike `contact_count`, no route pre-seeds `last_synced` on `g` (the list
route seeds the count); it relies purely on the processor's own query, so no route
change is needed. (2) `_inject_globals` runs on **every** response, including error
pages — wrap the `SELECT` in a `try/except` that falls back to `None`/"Never" (the
existing `contact_count()` already `try/except`s to `0`), so a DB failure during a
500 render cannot recurse into another 500. Because it is injected globally, it
appears on every page without each route passing it.

### 8.4 Edited-time in the contact list

`contacts.html` rows gain a muted **"edited {edited_at|friendly_date}"** hint.
`list_contacts` (via `_build_contact_query`, `models.py`) exposes `edited_at` per
row as a **correlated scalar subquery** column — `(SELECT edited_at FROM
contact_edits e WHERE e.contact_id = contacts.id) AS edited_at` — spliced into the
static `SELECT … FROM contacts` prefix, **not** a JOIN, so it adds no bound param
and cannot fan out rows or inflate the paginated `total` (the same no-JOIN
constraint that shaped CL-0025 and the CL-0026 `has_photo` column). `list_contacts`
also wraps this query as `SELECT COUNT(*) FROM (<query>)` for the paginated total;
SQLite discards the unused scalar column inside that `COUNT`, so the correlated
subquery adds no per-row cost on the count path (same as `has_photo`). A NULL
`edited_at` (never user-edited) renders nothing.

## 9. Error handling & idempotency

- **Per-contact isolation.** Each push (create/update) runs in its own
  `try/except`; a failure is logged server-side (never surfacing raw API text to
  the user, matching CL-0020) and counted in `skipped`, never aborting the run.
- **Idempotent create (INV-6).** `createContact` writes the returned `google_id`
  and `db.commit()`s **immediately** (per §5 Step 2's per-contact commit), so a
  crash-and-retry cannot create a second Google contact for the same local row.
  (People API `createContact` has no client-supplied idempotency key, so the guard
  is "persist the link at once".)
- **etag mismatch on update** → skip + report (§7), resolved next sync.
- **Partial run.** If the push phase dies mid-way, contacts already pushed have
  their `google_id`/`etag` persisted; `last_synced_at` is only advanced on a clean
  finish, so a re-run re-attempts the unpushed remainder (the dirty sets are
  recomputed from `edited_at` against the still-old `last_synced_at`). This mirrors
  the pull's "commit each page; token last" robustness (CL-0020).
- **Scope 403 on write** (should not happen given §3's pre-check) is caught,
  logged, and surfaced as "Google needs the write permission — reconnect."

## 10. Security

| Concern | Mitigation |
|---------|------------|
| Over-broad scope | Only `contacts` (read-write) is requested — the minimum for write-sync; no other Google scope. Disclosed on `/sync` + README (§3). |
| Destroying Google data | INV-2 read-modify-write preserves values the app doesn't manage; **no deletions** are ever sent (§2). `updatePersonFields` is restricted to managed fields, so unmanaged Google fields are never overwritten. |
| Silent overwrite of newer data | Timestamp LWW + fresh-etag backstop (§7, INV-3). A tie is Google-wins. |
| SSRF / new network surface | None new — all writes go through the same authenticated `people` service object and Google endpoints; no app-controlled URL is fetched (unlike the photo download, which is unchanged). |
| CSRF | Push rides the existing `POST /sync/start` with its validated `_csrf_token`; unchanged. |
| Secret handling | Token still stored `0600` under `~/.config/contact-list/`; scope change doesn't alter storage. `.gitignore` unchanged. |
| Credential leakage in errors | API error text is logged server-side only; the user sees a generic message (existing CL-0020 pattern, extended to the push path). |

## 11. Routes

No new route (no path added or removed), but two existing handlers change:

- **`POST /sync/start`** (the `start_sync` view) now runs the bidirectional sync;
  today `count, error = sync_contacts(...)` becomes `result = sync_contacts(...)`
  with attribute reads (§8.1). DESIGN.md §9's description for this row changes to
  "Trigger Google sync (import and export)".
- **`GET /sync`** (the `sync_page` view) gains a
  `needs_reconsent=google_sync.needs_reconsent(config)` argument passed to the
  template (so it is *not* literally unchanged — the path is, the handler body
  gains one line). `sync.html` must branch on `needs_reconsent` **before** the
  plain `is_authenticated` check, or a legacy-token user sees the ordinary
  "authorise" prompt with no signal that a new permission is needed. The template
  also gains a Reconnect button (§3) and the post-sync summary list (§8).

`POST /sync/authorize` and `POST /sync/disconnect` are unchanged.

## 12. Files & size budget

| File | Change | Est. LOC |
|------|--------|----------|
| `migrations/006_contact_edits.sql` | new — `contact_edits` table (`CREATE TABLE IF NOT EXISTS` only; no backfill, §4) | ~4 |
| `google_auth.py` | `SCOPES` → `contacts` | ~1 |
| `google_sync.py` | scope const; file-scope re-consent probe in `_load_credentials` + `needs_reconsent(config)` helper + `is_authenticated` (§3); Step-0 snapshot (`dirty_google_ids`); `skip_google_ids` param on `_upsert_person`; push phase (`_push_local_changes`, `_person_body_for_push`, `_apply_google_to_local` reuse); `SyncResult` | ~190 |
| `models.py` | `_mark_edited` (called by `create_contact`/`_write_contact`/`import_contact` per §4); `get_edited_at`; dirty-linked + local-only id-set helpers; `edited_at` scalar-subquery column in `_build_contact_query` | ~40 |
| `routes/sync.py` | unpack `SyncResult`; flash summary; pass `needs_reconsent` + skipped/conflict lists to template | ~15 |
| `routes/contacts.py` | detail route passes `edited_at` (via `get_edited_at`) to the template | ~3 |
| `app.py` | inject `last_synced` in `_inject_globals` (footer, §8.3), `try/except`→None like `contact_count()` | ~6 |
| `templates/sync.html` | re-consent notice; post-sync summary + skipped/conflict list | ~25 |
| `templates/contact_detail.html` | honest `Last edited` line replacing `Updated` (§8.2) | ~4 |
| `templates/contacts.html` | muted per-row `edited …` hint (§8.4) | ~4 |
| `templates/base.html` | footer `Last synced …` (§8.3) | ~2 |
| `README.md` | document two-way sync, the write-permission re-consent, and the no-delete caveat | ~10 |
| `DESIGN.md` | amend §4 (new §4.x table)/§4.4/§6.2/§8.2/§8.3/§9/§13 per the header | ~20 |

No new pip dependency; runtime deps stay at 6. Python source stays under the
< 100 KB soft target (measure before landing). **One idempotent schema migration**
(`006`, §4) — the only DB change.

## 13. Testing

Test-first (TDD), mocking the Google API client at the external boundary (DESIGN.md
§11 "Google sync tests mock the Google API client"), following the existing
`_FakeService`/`monkeypatch` pattern in `tests/test_hardening.py`. New coverage:

- **Scope re-consent** — a token with only `contacts.readonly` makes
  `is_authenticated` False and `needs_reconsent` True (forces re-auth, drives the
  "new permission needed" message); a token with `contacts` is accepted; **no**
  token makes both False (not "reconsent"). The scope probe reads the **token
  file's** scopes (a legacy token is detected even though the app now requests the
  write scope); a token file with no `scopes` key routes to reconsent too.
- **Single-source SCOPES (INV-5)** — assert `google_auth.SCOPES is
  google_sync.SCOPES` (one literal, imported), so the two can never diverge.
- **Honest `edited_at` (INV-1)** — `create_contact`/`update_contact`/
  `merge_contacts` (survivor) set `edited_at`; `import_contact` sets it on the
  create branch and on an update that changed data, but **not** on a no-op match; a
  `_upsert_person` **pull** does **not** touch it (assert `edited_at` unchanged
  after a pull re-imports a contact, including one that stores a photo). No backfill:
  a contact that only ever existed via the pull has **no** `contact_edits` row.
- **Dirty detection** — a contact the *pull* just wrote is **not** treated as
  dirty (not pushed); a contact the *user* edited after `prev_sync` **is** pushed.
- **Display** — the detail page shows `Last edited` from `edited_at` (not
  `updated_at`); the list row exposes `edited_at` without inflating `total`
  (mirror the CL-0026 `has_photo` no-JOIN dedup test); the footer shows
  `Last synced` (and "Never" when `sync_state` is empty).
- **Push-create** — a local-only contact triggers `createContact`; the returned
  `resourceName`/`etag` are stored; a second sync does **not** re-create it
  (INV-6, idempotency).
- **Push-update** — an edited linked contact triggers `updateContact` with the
  fresh etag and `updatePersonFields` limited to managed fields.
- **Multi-value preservation (INV-2)** — a Google contact with two phone numbers,
  edited locally, is pushed with **both** numbers present (ours updated, the
  second preserved) — the core data-loss regression test.
- **Conflict LWW (§7)** — both sides changed: Google newer → local overwritten,
  no `updateContact` call; local newer → `updateContact` called; equal → Google
  wins.
- **etag backstop (INV-3)** — `updateContact` raising a precondition error skips +
  reports, does not overwrite, and leaves the contact for the next sync.
- **No deletions (INV-4)** — a locally-deleted linked contact never calls
  `deleteContact`; assert the API's delete method is never invoked.
- **Multi-value match is position-based (INV-2)** — pushing an edit updates the
  Google contact's index-0 email/phone and leaves index-1+ untouched, even when our
  stored (formatted) value doesn't string-equal Google's raw stored value.
- **Missing `updateTime` (§7)** — a `get` whose `CONTACT` source has no
  `updateTime` resolves Google-wins (no `updateContact` call).
- **Per-contact isolation** — one push raising is caught, logged, counted in
  `skipped`, and does not abort the other pushes.
- **Report** — `SyncResult` counts match the operations performed; the `/sync`
  flash renders them.
- **Existing tests** that call `sync_contacts`/`_upsert_person` are updated for the
  new signature/return in the same commit.

## 14. Invariants

- **INV-1** — A contact's honest last-user-edit time lives in
  `contact_edits.edited_at`, written **only** by the user-facing `models.py`
  writers (`create_contact`, `_write_contact`, `import_contact`) and **never** by
  the sync pull (`_upsert_person`). "Locally dirty" = `edited_at > prev_sync`
  (`last_synced_at` read at sync start). A pull can therefore never make a contact
  look user-edited, and the displayed "Last edited" is never moved by a sync.
- **INV-2** — A push never removes a value the app does not manage: multi-valued
  Google fields (emails, phones) are read-modify-written to preserve secondary
  entries, and `updatePersonFields` only ever lists managed fields.
- **INV-3** — `updateContact` always carries the etag from a `get` performed in
  the same sync step; an etag/precondition failure skips-and-reports, never
  silently overwrites newer Google data.
- **INV-4** — v2.0 never calls `deleteContact`; no local deletion propagates to
  Google.
- **INV-5** — The scope requested is exactly `contacts` (nothing broader); `SCOPES`
  is a **single literal** (`google_auth.py` imports `google_sync.py`'s), so the two
  modules cannot diverge; and a legacy read-only token is rejected — via the token
  file's **own** recorded scopes, not the requested scopes (§3) — so no write is
  attempted without consent.
- **INV-6** — A push-create persists the new `google_id` in the same committed
  step, so a re-run never creates a duplicate Google contact for one local row.
  Load-bearing precondition: the push (Step 2) begins only after the pull (Step 1)
  has fully committed, so no push commit can flush a partially-applied pull.
- **INV-7** — On a conflict, the contact ends in exactly one of {Google applied
  locally, local pushed to Google, skipped-for-retry} — never a partial merge and
  never both writes.

## 15. Out of scope (v2.0)

- **Pushing deletions** to Google (the maintainer chose "edits + new contacts").
  A future opt-in would need a local tombstone table (deleted `google_id`s) since
  the row is gone; deferred.
- **Per-contact "don't sync to Google" opt-out** — v2.0 pushes all local-only
  contacts; a suppress flag is future work.
- **Editing/managing secondary emails/phones** — the app still models one each; it
  preserves but does not edit extras.
- **Automatic/background sync** — still user-triggered (DESIGN.md §7.2).
- **REST/JSON API** (the other half of the v2.0 line in DESIGN.md §13) — separate.
- **Photo push** — the app downloads Google photos (CL-0026) but does not upload
  local photos to Google; deferred.
