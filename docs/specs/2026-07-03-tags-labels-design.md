# Tags / Labels for Contacts — Design (CL-0037)

Status: **Implemented** (2026-07-03) — shipped as migration `008_tags.sql`,
`_normalize_tags`/`set_contact_tags`/`get_contact_tags`/`get_all_tags`/`_gc_orphan_tags`
+ `tags` params threaded through create/update/merge, the `?tag=` AND filter,
detail chips + list filter bar, and merge tag-union, with 31 tests (all green;
328 suite total). Passed `/cold-eyes` to convergence over
**9 loops**, findings decaying from structural (a merge-union `TypeError`, the
search/type `<form>`-vs-`url_for` filter-preservation mechanism, the
`maxlength` 50/500/2600 coherence) → filter & GC correctness (pagination silently
dropping the tag filter; the empty-state/Clear guards; a merge loser-delete that
orphaned a pruned tag, breaking INV-3; `update_contact` needing the `tags` param;
a `create_contact` persistence gap) → wording precision (INV-6 fan-out phrasing,
a fourth Google-sync delete path, import-note off-by-one). Final pass:
**0 Critical / 0 High / 0 Medium**; last LOW (a latent-trap note undercount) fixed.
Sign-off is self-delegated per the user's standing instruction (cold-eyes
converged, polish-only remainder). Date: 2026-07-03

> **Design decisions (Claude's call, 2026-07-03 — user delegated "leave it to
> you"; recommended defaults, flagged for later review):**
> 1. **Multi-tag filter = AND** (spec §5 — List filter): selecting `family` +
>    `local` shows only contacts carrying *both* tags. Reuses the existing
>    `id IN (subquery)` idiom, one condition per selected tag ANDed together.
> 2. **Tag creation = inline, auto-create / auto-delete** (spec §2, §4): tags are
>    typed as a comma-separated list on the contact form; a name not seen before
>    is created on save, and a tag whose last contact drops it is garbage-collected
>    so the filter bar never shows empty tags. No separate "manage tags" page.
> 3. **Plain chips** (spec §6): neutral chips, no per-tag colour and no colour
>    picker. Colour-coding is listed in §8 (Out of scope) as a later option.
> 4. **App-only first cut** (spec §8): tags are *not* added to CSV export/import
>    or Google sync in this change. Both are deferred to their own roadmap items
>    (see §8) to keep this spec to a single implementation plan. In-app **merge**
>    *does* preserve tags (union) — that is a data-loss guard, not a new surface.

Amends **DESIGN.md** in the same change-set as the implementation:
- **§9** (route table) — **no new route.** Tags are written through the existing
  `POST /contacts` (create) and `POST /contacts/<id>` (update) handlers via a new
  `tags` form field, and filtered through the existing `GET /contacts` list route
  via a repeated `?tag=` query param. The route table is unchanged.
- **§14** (file-size budget) — one new ~0.5 KB migration plus ~60 LOC of
  model/route and small template/CSS additions; the shipped-`.py` total stays
  well under the ~100 KB soft budget. **No new pip dependency** (DESIGN.md §3
  unchanged).
- **Data-model listing** (wherever DESIGN.md enumerates tables) — add the two new
  tables `tags` and `contact_tags`.

Sections: [1 Overview](#1-overview) · [2 Data model](#2-data-model) ·
[3 Tag-name normalization](#3-tag-name-normalization) ·
[4 Write path (create / update / merge)](#4-write-path-create--update--merge) ·
[5 List filter](#5-list-filter) · [6 Display & input UI](#6-display--input-ui) ·
[7 DESIGN.md amendments](#7-designmd-amendments) · [8 Out of scope](#8-out-of-scope) ·
[9 Testing](#9-testing) · [10 Invariants](#10-invariants).

## 1. Overview

Let the user group contacts under free-text labels ("family", "work", "gym") and
filter the list to just one group — or the intersection of several. Tags are
typed as a comma-separated list on the contact form, shown as chips on the
contact detail page, and exposed as a clickable filter bar on the contact list.

A tag is a shared, named row (`tags`); a contact-to-tag association is a row in a
many-to-many join table (`contact_tags`). A tag is created the first time it is
used and deleted when its last use is removed, so the set of tags a user sees is
always exactly the set currently applied to at least one contact.

Single-user, localhost only. Reuses the existing data-access layer (`models.py`),
the migration runner (`db.py`), the CSRF-on-POST guard (`app.py`), the existing
create/update/merge write paths, and the existing list-query builder
(`_build_contact_query`). **No new pip dependency. No new route.**

## 2. Data model

### 2.1 New tables — migration `008_tags.sql`

Two `CREATE TABLE IF NOT EXISTS` statements (idempotent under the migration
runner's crash window, mirroring 005/006/007) plus one index for the filter's
reverse lookup.

```sql
-- CL-0037: tags / labels for contacts (many-to-many).
--
-- `tags` holds one row per distinct label; `name` is UNIQUE with a case-
-- insensitive collation so "Family" and "family" collapse to one tag. The
-- stored casing is whatever was first typed. `contact_tags` is the join;
-- both FKs cascade so deleting a contact (or a tag) tidies the join
-- automatically. The index on tag_id backs the "contacts having tag T"
-- filter subquery (the PK already covers the "tags of contact C" direction).
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS contact_tags (
    contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id)     ON DELETE CASCADE,
    PRIMARY KEY (contact_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_contact_tags_tag ON contact_tags(tag_id);
```

`COLLATE NOCASE` folds ASCII case only — consistent with the app's existing
ASCII-oriented `first_letter()` bucketing. Non-ASCII case folding is out of
scope (a "Café"/"café" pair would be two tags; acceptable for a single-user
label set).

### 2.2 Data-access helpers (`models.py`)

```python
def _normalize_tags(raw: str) -> list[str]:
    """Parse a comma-separated tag field into a clean, de-duplicated list.

    Splits on commas; for each piece strips surrounding whitespace, collapses
    internal whitespace runs to a single space, drops empties, caps length at
    MAX_TAG_LEN chars, de-duplicates case-insensitively preserving the
    first-seen casing and order, then keeps at most MAX_TAGS (dropping any
    extras). Returns [] for a blank field.
    """

def set_contact_tags(
    db: sqlite3.Connection, contact_id: int, tag_names: list[str]
) -> None:
    """Replace a contact's tag set with `tag_names` (already normalized).

    Upserts each name into `tags` (INSERT OR IGNORE, matched case-insensitively),
    replaces the contact's rows in `contact_tags`, then garbage-collects any tag
    left with no contacts. NO transaction of its own — the caller
    (create/update/merge) composes it into their existing `with db:` block, the
    same pattern `_write_contact` uses for custom fields.
    """

def get_contact_tags(db: sqlite3.Connection, contact_id: int) -> list[str]:
    """The contact's tag names, ordered by name (case-insensitive)."""

def get_all_tags(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every in-use tag with its contact count, for the list filter bar.

    `SELECT t.name, COUNT(ct.contact_id) AS cnt FROM tags t
     JOIN contact_tags ct ON ct.tag_id = t.id GROUP BY t.id
     ORDER BY t.name COLLATE NOCASE`.
    The INNER JOIN means a hypothetical orphan tag (0 contacts) never appears,
    independent of GC. The `COLLATE NOCASE` order matches `get_contact_tags`'s
    case-insensitive ordering, so chips sort identically on the list and detail.
    """

def _gc_orphan_tags(db: sqlite3.Connection) -> None:
    """Delete tag rows no contact references any more (called with no commit
    of its own — runs inside the caller's transaction): `DELETE FROM tags
    WHERE id NOT IN (SELECT tag_id FROM contact_tags)` (INV-3)."""
```

`set_contact_tags` is set-to-state (the caller passes the desired final tag
list), so a double-submit is idempotent. Internally:

1. For each name: `INSERT OR IGNORE INTO tags (name) VALUES (?)`, then resolve
   its id with `SELECT id FROM tags WHERE name = ? COLLATE NOCASE`.
2. `DELETE FROM contact_tags WHERE contact_id = ?`.
3. `executemany('INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)', …)`.
4. `_gc_orphan_tags(db)` — `DELETE FROM tags WHERE id NOT IN
   (SELECT tag_id FROM contact_tags)` (INV-3).

**Caps (the single authoritative statement — referenced, not repeated, from §3
and §6).** Two module constants, both **50**, enforced server-side in
`_normalize_tags`, which is the authoritative cap:

- `MAX_TAG_LEN` (**50**) — the *per-tag* length cap. A per-comma-piece cap cannot
  be expressed with an HTML `maxlength`, so the server truncates (§3).
- `MAX_TAGS` (**50**) — the *number* of tags per contact, matching the existing
  hard-coded 50-item custom-field limit (`if len(custom_fields) > 50` in
  `_validate_custom_fields`, `routes/contacts.py`). Note the enforcement differs:
  the custom-field cap raises a validation error, whereas over-`MAX_TAGS` tags are
  **silently dropped** by `_normalize_tags` (dropping the surplus is friendlier
  than rejecting the whole save for a label field).

The form input carries `maxlength="2600"` — a deliberate safe over-bound of
`MAX_TAGS × (MAX_TAG_LEN + 2)` (the true server-valid maximum is slightly lower —
50 × 50 chars + 49 × 2 separators = 2598 — but rounding up guarantees the browser
guard **never clips a server-valid tag set**). It is a defense-in-depth bound, not
the authoritative cap.

## 3. Tag-name normalization

`_normalize_tags` is the single choke-point for what becomes a tag, so create,
update, and merge all apply identical rules (INV-1):

- **Delimiter:** comma. A tag therefore cannot itself contain a comma — acceptable
  for short labels; documented in the form hint.
- **Whitespace:** outer strip + inner runs collapsed to one space
  (`"  close  friends "` → `"close friends"`).
- **Empty pieces dropped:** `"a,,b, ,c"` → `["a", "b", "c"]`.
- **Length cap:** pieces longer than `MAX_TAG_LEN` (50) are **truncated** to the
  cap (not rejected — a silent reject would lose the tag; truncation keeps the
  intent). Truncation happens before dedup.
- **Count cap:** after dedup, at most `MAX_TAGS` (50) tags are kept and any
  extras are dropped — mirroring the custom-field count cap, so a pathological
  pasted comma-blob cannot flood the shared `tags` table with thousands of rows.
- **Case-insensitive de-dup, order-preserving:** `"Work, work, WORK"` →
  `["Work"]` (first-seen casing wins). Matching an existing DB tag is also
  case-insensitive (§2.2 step 1), so re-adding "work" to a contact that a
  *different* contact tagged "Work" reuses the existing row and casing.

No character allow-list beyond "not a comma / not empty after strip" — over-
validating label text is user-hostile and the values are Jinja-autoescaped on
display, so there is no injection surface (XSS handled by autoescaping; SQL by
parameterization).

## 4. Write path (create / update / merge)

### 4.1 create / update

Three write functions in this section gain a `tags: list[str] | None = None`
parameter (`merge_contacts` gains it too — §4.2 — for four in total), and
**two of these three each make their own `set_contact_tags` call** (because
`create_contact` does **not** route through `_write_contact` — it has its own
INSERT path):

- `create_contact` — inside its **own** `with db:` block, after its custom-field
  `executemany`, add `set_contact_tags(db, contact_id, tags or [])`.
- `_write_contact` — after its custom-field re-insert, add the same
  `set_contact_tags(db, contact_id, tags or [])`. `_write_contact` has **no**
  transaction of its own — its callers (`update_contact`, `merge_contacts`) wrap
  it in `with db:` — so the tag write joins whichever transaction the caller
  opened.
- `update_contact` — the thin `with db: _write_contact(...)` wrapper the route
  actually calls; it must **accept `tags` and forward it** to `_write_contact`, or
  `update_contact(tags=…)` is unreachable. (It makes no `set_contact_tags` call of
  its own — `_write_contact` does that.)

Either way a failed tag write rolls back the whole contact write (INV-5).
`import_contact` INSERTs directly and is **not** given a tags param (CSV import
carries no tags in this scope, §8).

**Imports:** add `_normalize_tags, get_contact_tags, get_all_tags` to
`routes/contacts.py`'s `from models import (...)` block (`_normalize_tags` for the
create/update/list routes; `get_contact_tags` for the edit-seed + detail views;
`get_all_tags` for the list filter bar), and `_normalize_tags, get_contact_tags`
to `routes/merge.py`'s block (for §4.2's merge wiring).

> **Latent-trap note (verified 2026-07-03).** `set_contact_tags(..., tags or [])`
> is called **unconditionally**, so any caller reaching `_write_contact` without a
> `tags` argument would *wipe* that contact's tags. This is safe today only
> because the tag-unaware writers that update existing contacts — the Google pull's
> `_upsert_person` (`google_sync.py`) and `import_contact` (`models.py`) — each
> write via their **own** raw `UPDATE contacts`, **not** through
> `_write_contact`/`update_contact`. A future refactor that points either at
> `update_contact` must pass `tags` through, or it will silently clear tags.

The route layer parses the field once:

```python
tags = _normalize_tags(request.form.get('tags', ''))
```

and threads it through `create_contact(...)` / `update_contact(...)`. On a
validation error re-render, the raw `tags` string is passed back to the template
so the user's typed text survives (mirroring how `custom_fields` are echoed).

**The `edit` GET route must seed the field.** Because `set_contact_tags` is
unconditional (latent-trap note above), the edit form **must** render the
contact's current tags — the `edit` view passes
`tags_str=', '.join(get_contact_tags(db, contact_id))` (see §6), so submitting an
unchanged edit re-writes the same tags rather than wiping them. Omitting this
seed would clear every contact's tags on the next plain save.

### 4.2 merge — tags are unioned (data-loss guard)

Merging deletes the loser contacts; their `contact_tags` rows cascade away. So
the **survivor must be given the union** of all involved contacts' tags, or
loser-only tags vanish silently. Merge is a **two-route** flow (`routes/merge.py`):
`merge_preview` renders `merge.html`, and `merge_apply` reads the submitted form
and calls `merge_contacts`. Tags thread through both:

- **`merge_preview`** computes the union of every involved contact's tags and
  passes it (as one comma string) to `merge.html` to pre-fill an **editable**
  `tags` input — the same affordance as the other merged fields, so the user can
  prune before confirming:

  ```python
  # `tag_union`, not `union` — `merge_preview` already binds a `union` dict for
  # the custom-field aggregation (routes/merge.py), so avoid shadowing it.
  tag_union = _normalize_tags(
      ', '.join(
          name
          for cid in [survivor_id, *loser_ids]
          for name in get_contact_tags(db, cid)
      )
  )
  ```

  (flattening the per-contact `list[str]` results into one comma string, then
  re-normalizing to de-dup across contacts).

- **`merge_apply`** reads the (possibly edited) field back and passes it to the
  merge:

  ```python
  tags = _normalize_tags(request.form.get('tags', ''))
  merge_contacts(db, survivor_id, loser_ids, fields, customs, tags=tags)
  ```

`merge_contacts` gains a `tags` param and forwards it to `_write_contact` →
`set_contact_tags`, so the survivor ends up carrying exactly the confirmed tag
set (the union by default, minus anything the user pruned). The pre-fill is the
union; the authoritative applied value is whatever the form submits (INV-8).
*Edge case:* if the combined distinct tag set exceeds `MAX_TAGS` (50),
`_normalize_tags` caps the pre-fill and the surplus is dropped before the user
sees it — an accepted, vanishingly-rare loss for a single-user label set (noted
on INV-8).

**Concrete edits (matching the exhaustive style of §5/§6):**
1. `merge_preview` — add `tags_str=', '.join(tag_union)` to its existing
   `render_template('merge.html', …)` call (it currently passes only
   `contacts, survivor_id, loser_ids, core, customs`).
2. `merge.html` — add an editable `<input name="tags" maxlength="2600"
   value="{{ tags_str }}">` (a "Tags" row in the merge form), mirroring the
   contact form's field.
3. `merge_apply` — parse `tags = _normalize_tags(request.form.get('tags', ''))`
   and pass `tags=tags` to `merge_contacts` (currently
   `merge_contacts(db, survivor_id, loser_ids, fields, customs)`).
4. `merge_contacts` — add the `tags` param, forward it to `_write_contact`, and
   **call `_gc_orphan_tags(db)` after the loser-delete loop** (see §4.3 — merge is
   a third GC path, not covered by `delete_contact`).

### 4.3 delete / GC paths

There are **three** contact-delete paths that can orphan a tag, and each must GC:

- `delete_contact` (single) — `_gc_orphan_tags(db)` inside its **existing**
  `with db:` block, after the delete (INV-4).
- `bulk_delete` (batch) — has no transaction of its own; it loops `delete_contact`
  per id (`routes/contacts.py`), so it inherits the GC per iteration and needs
  **no separate change**.
- `merge_contacts` (survivor + loser deletes) — deletes losers via its own
  `DELETE FROM contacts` (not `delete_contact`), **after** `_write_contact` has
  already run `set_contact_tags`'s GC on the survivor. Consider a loser-only tag
  the user pruned (or the `MAX_TAGS` cap trimmed): at survivor-GC time the loser
  still holds its `contact_tags` row, so the tag survives that GC. It orphans only
  once the loser is deleted, a moment later in the same transaction. So
  `merge_contacts` calls `_gc_orphan_tags(db)` **after** the loser-delete loop,
  inside its `with db:` (§4.2 edit 4) — without it, INV-3 cannot hold on the merge
  path.

(Even without GC an orphan tag is invisible — `get_all_tags` inner-joins — but GC
keeps the table honest and makes INV-3 testable.)

These GC paths depend on the `contact_tags` cascade firing **before** the
same-transaction GC runs, which requires `PRAGMA foreign_keys=ON` — already set
per-connection in `db.py` (the same pragma the CL-0039 favourite cascade relies
on), so no new setup is needed.

**A fourth delete path exists but is not GC'd inline:** the Google pull's
`_upsert_person` deletes a tombstoned contact via its own
`DELETE FROM contacts WHERE google_id = ?` (`google_sync.py`). This can leave a
tag orphaned, but the orphan is invisible (`get_all_tags` inner-joins) **and
self-healing**: `_gc_orphan_tags` is global (`DELETE FROM tags WHERE id NOT IN
(SELECT tag_id FROM contact_tags)`), so the next tag write on *any* contact sweeps
it. Adding a GC call to the sync-delete path is deliberately **out of scope** here
(it touches the sync module for zero user-visible benefit); it can be a follow-up
if the transient orphan ever matters.

## 5. List filter

`_build_contact_query` gains a `tags: list[str] | None = None` parameter. For
**AND** semantics, each selected tag contributes one `id IN (subquery)`
condition, ANDed with the others (and with the existing search/type/letter
conditions) by the function's existing `' AND '.join(conditions)`:

```python
for name in (tags or []):
    conditions.append(
        'id IN (SELECT ct.contact_id FROM contact_tags ct '
        'JOIN tags t ON t.id = ct.tag_id WHERE t.name = ? COLLATE NOCASE)'
    )
    params.append(name)
```

This reuses the exact `id IN (…)` idiom already used for custom-field search, so
it needs no new join on the outer query and — being a scalar membership test —
does **not** fan out rows or inflate the `COUNT(*)`-over-subquery total (the
CL-0025 / CL-0039 non-fan-out constraint, INV-6). Each condition is one bound
param (the tag name); N tags → N conditions → "has all N tags".

`list_contacts` gains a matching `tags` param and forwards it to
`_build_contact_query` (the tag conditions are part of the shared `query`, so the
`COUNT(*)` and the `SELECT` both see them). The route:

```python
tags = _normalize_tags(', '.join(request.args.getlist('tag')))
```

`getlist('tag')` collects a repeated `?tag=family&tag=work` param; re-normalizing
dedups and cleans it. `contact_list` passes `tags` to `list_contacts` and to the
template. **Three existing details must be updated** so an active tag filter
survives every other navigation (INV-7):

- **Nav-badge seed guard.** `if not (search or contact_type or letter):` becomes
  `if not (search or contact_type or letter or tags):` — an active tag filter is
  a filtered view, so it must not seed `g.contact_count` with a partial total.
- **The `url_for` links** that forward the current filter params — the sort-header
  links ("Name"/"Type"), the alpha-nav / "All" links, **and the Prev/Next
  pagination links** — each gain `tag=active_tags` (a list → Flask emits repeated
  params) so tags survive a sort, a letter click, **and paging**. (The pagination
  links are easy to miss: without `tag=`, clicking "Next" on a tag-filtered result
  that spills to page 2 silently drops the filter and shows the unfiltered page.)
- **The search / type `<form>`** — the `q` search box and the `type` `<select>`
  live in a single GET `<form>` (`contacts.html`, near the top), **not** in
  `url_for` links, so a `tag=` kwarg cannot reach them. To keep active tags across
  a search submit or a type change, the form gets one hidden
  `<input type="hidden" name="tag" value="{{ t }}">` per active tag (a
  `{% for t in active_tags %}` loop inside the form). Without this, submitting the
  search or changing the type dropdown would silently clear the tag filter.

## 6. Display & input UI

- **Form (`contact_form.html`) — input.** A single text input in a new "Tags"
  `form-group`, placed as the **last group inside the `Basic Info` `<fieldset>`**
  (right after the Notes group, before that fieldset's closing tag — so it sits in
  a fieldset like every other field, not orphaned between fieldsets):
  `<input name="tags" type="text" maxlength="2600" value="{{ tags_str }}">` with a
  hint "Separate tags with commas". `tags_str` is the contact's current tags
  joined `", "` on edit (the `edit` view passes
  `tags_str=', '.join(get_contact_tags(db, contact_id))`), the echoed raw string on
  a validation-error re-render, or `''` on new (the `new_contact` view passes
  `tags_str=''` explicitly — the form guards every field value, so don't rely on
  Jinja default-undefined rendering). The `maxlength` is the defense-in-depth
  aggregate bound from §2.2 (never the authoritative cap).
  **Deliberate departure from ROADMAP CL-0037** ("tag chips on the contact form
  *and detail page*"): the form uses a plain comma **text input**, not an
  interactive chip widget — a text field matches the app's server-rendered,
  minimal-JS convention and is the shortest correct input. Chips remain the
  *display* affordance (detail page + list filter bar). An interactive chip
  editor is a future polish item (§8).
- **Detail (`contact_detail.html`) — chips.** A dedicated "Tags" section in the
  detail **card body** (a block of its own, *not* inside the `.detail-header`
  `<div>` that holds the name / type badge / favourite form — the header nests an
  inline form, so tags go in the body to avoid inheriting that inline flow),
  rendering each tag as a chip that links to the filtered list:
  `<a class="tag-chip" href="{{ url_for('contacts.contact_list', tag=t) }}">{{ t }}</a>`.
  The `detail` view passes `tags=get_contact_tags(db, contact_id)`. Shown only
  when the contact has tags.
- **List (`contacts.html`) — filter bar.** Below the alpha-nav, a tag filter bar
  (rendered only if `all_tags` is non-empty) of chips, one per in-use tag, each
  showing its count and toggling itself in/out of the active filter. For each
  tag `t` in `all_tags`, the template computes a target tag-list: active tags
  **minus** `t.name` if `t.name` is currently active (a de-select link), else
  active tags **plus** `t.name` (an add link). Both the "is it active?" test and
  the "minus" subtraction compare **case-insensitively** (against `active_tags_lc`,
  by `t.name | lower`), so a hand-typed `?tag=WORK` still de-selects a stored
  `Work` chip. The chip then links to
  `url_for('contacts.contact_list', tag=target, q=search, type=contact_type, letter=letter)`,
  forwarding the active `q`/`type`/`letter` so toggling a tag preserves those
  filters (§5). (It does **not** carry `sort`/`dir`/`per_page` — consistent with
  the existing alpha-nav links, which also reset the sort; a conscious match, not
  an oversight.) Active chips get an `.active` class. `contact_list` passes
  `all_tags=get_all_tags(db)`, `active_tags=tags`, and `active_tags_lc`
  (a lower-cased set of the active names) for the membership test. **Per-row tag
  chips are intentionally omitted** — keeping them off the table preserves the
  `<thead>`/column alignment, as favourites did (CL-0039 §5). Case-insensitive
  membership test in Jinja: `t.name | lower in active_tags_lc` is exact.
- **Filtered-empty guards (`contacts.html`).** AND-filtering two tags can
  legitimately return zero rows, so the two existing "is this a filtered view?"
  guards must also test tags, or a zero-result tag filter renders the wrong empty
  state / hides the Clear affordance:
  - The **empty-state** guard (`{% if search or contact_type or letter %}`) gains
    `or tags`, so a no-match tag filter shows "No contacts match your filters"
    (with a Clear-filters link) instead of the first-run "No contacts yet" copy.
  - The toolbar **Clear** guard (`{% if search or contact_type %}`) gains
    `or letter or tags` so a tag-only (or letter-only) filter still offers Clear.
    (Adding `letter` here also fixes a pre-existing omission — surfaced, not
    silently expanded: the Clear button currently doesn't show for a letter-only
    filter. Flag to the user; include only if approved.)
- **CSS (`static/style.css`):** a small `.tag-chip` rule (neutral pill: subtle
  background, rounded, small text) and an `.tag-chip.active` variant for the
  filter bar's selected state. No colour picker, no JS.

## 7. DESIGN.md amendments

Applied in the same change-set as the implementation:

- **§9 route table** — **no new route** (tags ride the existing create/update POST
  and list GET).
- **§9.1 Query Parameters for `/contacts`** — add one row: `tag` — "Filter by tag
  (repeatable; contacts matching **all** given tags)", matching the existing
  `q`/`type`/`letter`/`per_page` rows. (While editing this table, also refresh the
  stale `q` row — it still reads "matches name, email, phone" but CL-0025 extended
  search to notes + custom-field values; a free one-line fix in the same pass.)
- **§14 file-size budget** — note the additions; the shipped-`.py` total remains
  under the ~100 KB soft target. No dependency-budget change.
- **§4 Data Model** — add a subsection for `tags` and `contact_tags` (and the
  `idx_contact_tags_tag` index). Note: DESIGN.md §4 currently documents only
  `contacts`/`custom_fields`/`sync_state`/`contact_edits` — the later companion
  tables `contact_photos` (005) and `contact_favourites` (007) were never added
  there, so this is a fresh subsection, not an insertion "alongside" existing
  ones. (Back-filling photos/favourites is out of scope here — flag to the user.)
  The join table carries no `created_at`/`updated_at`, so note the deliberate
  deviation from DESIGN.md §4.5 "Schema Conventions" (a pure many-to-many join
  legitimately omits timestamps). While editing §4, also fix §4.5's own stale
  parenthetical "no existing table carries both" — the `contacts` table **does**
  carry both `created_at` and `updated_at` — so the corrected convention reads
  that `contacts` complies while the companion tables (photos/favourites/tags)
  deliberately don't.

## 8. Out of scope

- **CSV export / import of tags.** A `tags` column (semicolon-separated) so tags
  survive a backup/restore round-trip. Deferred to its own roadmap item — it
  touches the export writer, the import parser, and the import-profile mapping,
  which is a separate cold-eyes surface.
- **Google sync of tags** (mapping to Google contact *groups*). The People API
  group model is fiddly and orthogonal to the local label store; its own roadmap
  item.
- **Per-tag colours** and a colour picker. Neutral chips ship first; colour is a
  later polish item (would add a `color` column to `tags` and a picker to the
  form).
- **A dedicated "manage tags" page** (global rename / delete / merge of tags).
  Inline auto-create / auto-GC covers the common case; bulk tag management is a
  future item.
- **Per-row tag chips on the list table** (see §6 rationale).
- **Tag rename** (there is no rename affordance; a user "renames" by retagging
  contacts, which GCs the old tag).

## 9. Testing

New tests mirror the existing `tests/` structure (`test_models.py`,
`test_routes.py`):

- **Migration/schema:** `tags`, `contact_tags`, and `idx_contact_tags_tag` exist
  after init; re-init is a no-op (idempotent).
- **Normalization (`_normalize_tags`):** comma split; outer strip + inner
  whitespace collapse; empty pieces dropped; over-length piece truncated to 50;
  count capped at `MAX_TAGS` (a 60-item field keeps 50, drops the rest);
  case-insensitive order-preserving de-dup (`"Work, work"` → `["Work"]`); blank
  field → `[]`.
- **`set_contact_tags`:** creates tag rows and associations; re-setting a
  different list replaces associations and GCs a now-orphan tag; case-insensitive
  reuse (contact A "Work", contact B "work" → one `tags` row, both associated);
  set-to-same is idempotent (no dup rows).
- **`get_contact_tags` / `get_all_tags`:** per-contact names ordered; `get_all_tags`
  returns in-use tags with correct counts and excludes a zero-contact tag. (That
  last case inserts an orphan `tags` row **directly** — bypassing `set_contact_tags`,
  which would GC it — so the test isolates the inner-join guard from the GC guard.)
- **Filter (AND):** a contact tagged {a, b} is returned for `?tag=a&tag=b`; a
  contact tagged only {a} is **not**; an unknown tag → empty; a single `?tag=a`
  returns all a-tagged contacts; matching is case-insensitive (`?tag=WORK` hits a
  "work" contact).
- **No fan-out:** a contact carrying **both** selected tags appears exactly once
  in the results and is counted once in `total` — the `id IN` membership test
  cannot fan the row out the way a JOIN would. (Filtering legitimately reduces
  `total` to the distinct matching contacts; this asserts the count isn't
  *inflated* above that, not that it's unchanged.)
- **Transaction composition (INV-5):** a forced failure after `set_contact_tags`
  within the caller's `with db:` rolls back both the contact row/edit and its
  tag rows — no half-applied write (mirrors the custom-field atomicity test).
- **create / update round-trip (routes):** POST create with `tags="a, b"` →
  detail shows a, b; POST update changing to `tags="b, c"` → a is gone (and GC'd
  if unique to it), c added; validation-error re-render echoes the typed `tags`
  string.
- **Merge unions tags:** merging a {a} contact into a {b} survivor yields a
  survivor tagged {a, b} when the pre-filled `tags` field is submitted unchanged;
  and a **prune** path — submitting the merge with `a` removed from the `tags`
  field yields a survivor tagged only {b} (the applied set is what the form
  submits, INV-8), **and** asserts the now-unused `a` row is gone from `tags`
  (merge-path GC, INV-3).
- **Delete GC:** deleting the sole contact of tag `x` (single delete and
  bulk-delete) removes the `x` row from `tags` (INV-4).
- **Filter-preservation (routes):** with an active `?tag=` filter, a sort-header
  link, an alpha-nav (letter) link, **and a Prev/Next pagination link** keep the
  `tag` param; a **search submit and a type change** also keep it (via the form's
  hidden `tag` inputs); the nav-badge count is **not** seeded from the filtered
  total (INV-7).
- **Filtered-empty state (routes/template):** an AND-filter miss (`?tag=a&tag=b`
  with no contact having both) renders the "No contacts match your filters" empty
  state, not "No contacts yet", and a tag-only filter shows the Clear affordance.

## 10. Invariants

| ID | Invariant | Test surface |
|----|-----------|--------------|
| INV-1 | `_normalize_tags` is the single normalization choke-point for tag **writes**: create, update, and merge all pass tag text through it, so casing/whitespace/dedup/count rules are identical on every write path. (The list **filter**'s case-insensitive matching is provided separately by `COLLATE NOCASE` in the filter subquery, not by normalization.) | `test_models.py` normalize + create/update/merge round-trips |
| INV-2 | Tag-name uniqueness is case-insensitive: at most one `tags` row per name under `COLLATE NOCASE`; re-adding a differently-cased spelling reuses the existing row. | `test_models.py` case-insensitive reuse |
| INV-3 | No orphan tag ever **surfaces**: `get_all_tags` inner-joins, so a tag with zero `contact_tags` rows never appears. The write path and all three *user-facing* delete paths (single, bulk, **merge**) GC eagerly; because `_gc_orphan_tags` is global, any later tag write also sweeps stragglers (e.g. a tag transiently orphaned by the Google-sync tombstone delete, which does not GC inline — §4.3). | `test_models.py` GC after retag, after delete, and after a merge that prunes a loser-only tag |
| INV-4 | Deleting a contact (single or bulk) removes its `contact_tags` rows (cascade) and GCs any tag it was the last user of. | `test_models.py`/`test_routes.py` cascade + GC |
| INV-5 | Tag writes are atomic with the contact write: `set_contact_tags` runs inside the caller's `with db:`; a failed tag write rolls back the contact write. | `test_models.py` transaction composition |
| INV-6 | The tag filter uses a scalar `id IN (subquery)` membership test, **not** a JOIN, so each matching contact is returned exactly **once** however many of its tags match — no row fan-out inflates the result set or the `COUNT(*)`-over-subquery `total`. (Filtering itself legitimately *reduces* the total to the distinct matching contacts; the invariant is about no *inflation*, not no change.) N selected tags select contacts having **all** N (AND). | `test_models.py` AND semantics + no-fan-out (a contact matching several selected tags appears once) |
| INV-7 | An active `?tag=` filter is treated as a filtered view: it never seeds `g.contact_count`; it is preserved across every other navigation — sort, letter, type, search, **and pagination**; and a no-match tag filter renders the filtered-empty state (with the Clear affordance), not the first-run "No contacts yet" copy. | `test_routes.py` badge-seed + link-preservation (incl. a paging case) + filtered-empty state |
| INV-8 | Merge is tag-loss-free **by default**: the merge form is pre-filled with the union of all merged contacts' tags, and the survivor is written with exactly the submitted set — so a loser-only tag is dropped only if the user explicitly prunes it (or, in the rare case the combined set exceeds `MAX_TAGS`, is trimmed by the cap). | `test_models.py`/`test_routes.py` merge union + prune path |
