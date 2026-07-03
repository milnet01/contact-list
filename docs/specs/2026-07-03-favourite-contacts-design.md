# Favourite / Pinned Contacts — Design (CL-0039)

Status: **Implemented** (2026-07-03) — design confirmed by the user; passed
`/cold-eyes` to convergence (4 loops: findings decayed from doc-accuracy fixes
→ a real nested-`<form>` structural catch → wording polish; final pass 0
Critical / 0 High / 0 Medium). Shipped as migration `007_favourites.sql` +
`set_favourite`/`is_favourite` + the `toggle_favourite` route + list/detail star
toggles, with 21 tests (all green).
Date: 2026-07-03

> **Confirmed design decisions (user-approved 2026-07-03):**
> 1. **Sort behaviour = "always pinned to top"** (spec §3 — Sort behaviour):
>    favourites form a block at the top of the list, sorted among themselves by
>    whatever sort is active; everyone else follows. Matches the roadmap's "sort
>    favourites first".
> 2. **Schema = a `contact_favourites` companion table** (spec §2 — Data model),
>    not a boolean column on `contacts`. Follows the project's own
>    idempotent-migration pattern (005_photos, 006_contact_edits) and the ROADMAP
>    CL-0039 bullet's own "use a new table or a guarded migration" guidance, since
>    SQLite has no `ADD COLUMN IF NOT EXISTS`.
> 3. **No "favourites-only" filter** in this scope (YAGNI — pinning already
>    surfaces them). Listed in spec §8 (Out of scope) as a future option.

Amends **DESIGN.md** in the same change-set as the implementation:
- **§9** (route table) — adds one route: `POST /contacts/<id>/favourite`.
- **§14** (file-size budget) — one new ~0.3 KB migration plus ~20 LOC of
  model/route and a small template/CSS addition; the shipped-`.py` total stays
  well under the ~100 KB soft budget. No new dependency (DESIGN.md §3 unchanged).

Sections: [1 Overview](#1-overview) · [2 Data model](#2-data-model) ·
[3 Sort behaviour](#3-sort-behaviour) · [4 Toggle route](#4-toggle-route) ·
[5 Display](#5-display) · [6 DESIGN.md amendments](#6-designmd-amendments) ·
[7 Testing](#7-testing) · [8 Out of scope](#8-out-of-scope) ·
[9 Invariants](#9-invariants).

## 1. Overview

Let the user "star" a contact so their most-contacted people pin to the top of
the list. A star toggle appears on each list row and on the contact detail page.
Favourite status is a per-contact boolean, stored as the presence/absence of a
row in a `contact_favourites` companion table.

Single-user, localhost only. Reuses the existing data-access layer (`models.py`),
the migration runner (`db.py`), the CSRF-on-POST guard (`app.py`), and the
`_safe_ref` return-target helper (`routes/contacts.py`). **No new pip dependency.**

## 2. Data model

### 2.1 New `contact_favourites` table — migration `007_favourites.sql`

A companion table (not a column on `contacts`) so the migration is idempotent
under the runner's crash window — SQLite has no `ADD COLUMN IF NOT EXISTS`, but
`CREATE TABLE IF NOT EXISTS` re-runs cleanly. Mirrors `contact_photos` (005) and
`contact_edits` (006). Presence of a row = the contact is a favourite; cascade
delete keeps it in lockstep with the contact. (`created_at` is kept for symmetry
with 005/006 — no code reads it.)

```sql
-- CL-0039: favourite / pinned contacts.
CREATE TABLE IF NOT EXISTS contact_favourites (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

No index needed beyond the PK: lookups are by `contact_id` (the PK) and the
list-ordering uses a correlated `EXISTS` on the PK.

### 2.2 Data-access helpers (`models.py`)

```python
def set_favourite(db: sqlite3.Connection, contact_id: int, favourite: bool) -> None:
    """Star (favourite=True) or un-star (False) a contact. Idempotent."""
    if favourite:
        db.execute(
            'INSERT OR IGNORE INTO contact_favourites (contact_id) VALUES (?)',
            [contact_id],
        )
    else:
        db.execute(
            'DELETE FROM contact_favourites WHERE contact_id = ?', [contact_id]
        )
    db.commit()

def is_favourite(db: sqlite3.Connection, contact_id: int) -> bool:
    """True iff the contact is currently a favourite (for the detail page)."""
    row = db.execute(
        'SELECT 1 FROM contact_favourites WHERE contact_id = ?', [contact_id]
    ).fetchone()
    return row is not None
```

`set_favourite` is a set-to-state operation (not a blind toggle): the caller
passes the desired end state, so a double-submit is idempotent — no risk of two
rapid clicks cancelling out.

## 3. Sort behaviour

Favourites are **always pinned to the top** of the result set, regardless of the
active sort column or sort direction. Pinning applies *within the filtered set* —
a favourite excluded by the active search/type/letter filter still does not
appear; only the ordering of the matching rows changes. Within the favourites
block and within the non-favourites block, the user's chosen sort applies as
normal.

Implementation: `_build_contact_query` gains one scalar column, appended after
the existing `edited_at` scalar and before `FROM contacts` in the SELECT prefix.
It uses the same non-fan-out pattern as `has_photo` (an `EXISTS`) and `edited_at`
(a scalar `SELECT` subquery), so it does **not** inflate the
`COUNT(*)`-over-subquery total:

```sql
EXISTS (SELECT 1 FROM contact_favourites f WHERE f.contact_id = contacts.id)
    AS is_favourite
```

and `list_contacts` prepends it to the ORDER BY:

```python
query += f' ORDER BY is_favourite DESC, {order_col} {direction}'
```

`is_favourite DESC` is hard-coded — never inverted by `sort_dir` — so favourites
stay pinned on top for **both** sort directions (INV-2). `is_favourite` is
emitted as a column on every list row (rows are `sqlite3.Row`, passed through
`contact_list` unchanged), so the template renders the star state without a
second query.

## 4. Toggle route

One route in `routes/contacts.py` (core CRUD module). The name `toggle_favourite`
describes the UI affordance; the handler *sets* the posted desired end-state
(§2.2), it does not blind-flip:

```python
@bp.route('/contacts/<int:contact_id>/favourite', methods=['POST'])
def toggle_favourite(contact_id: int):
    db = get_db()
    if not get_contact(db, contact_id):
        abort(404)
    set_favourite(db, contact_id, request.form.get('favourite') == '1')
    ref = _safe_ref(_get_ref())
    if ref:
        return redirect(ref)          # back to the list at its page/filters
    return redirect(url_for('contacts.detail', contact_id=contact_id))
```

- **CSRF:** POST-only; the app's existing `before_request` guard validates the
  per-session CSRF token on every POST, so a missing/invalid token is rejected
  (403) before the handler runs. The form carries a hidden field **named
  `_csrf_token`** with value `{{ csrf_token() }}` — the field name is
  `_csrf_token` (what `app.py` reads via `request.form.get('_csrf_token')`);
  `csrf_token()` is only the Jinja helper that yields the value.
- **Desired-state form field:** the button posts `favourite=1` when the contact
  is not yet a favourite, `favourite=0` when it is (the template knows the
  current state from `is_favourite`). Anything other than `'1'` — including a
  missing or garbled `favourite` field — resolves to un-star (by design; the POST
  is still CSRF-guarded, so this is not a security issue).
- **Return target:** reuses `_safe_ref`/`_get_ref` (local-paths-only). The
  **list** row form submits a `ref` (see §5), so starring on list page 3 returns
  to page 3 with filters intact. The **detail** page form deliberately submits
  **no `ref`**, so the empty-ref branch redirects back to that contact's detail
  page. (The `detail` view does compute a `ref` for its other links, but the star
  form must not forward it, or the redirect would bounce to the list.) Note: after
  starring from the list, the contact pins to the top (INV-2) and may move to
  page 1, so it can legitimately leave the page-3 view the user returns to —
  intended behaviour, not a bug (worth a comment in the test that asserts it).
- **404** on an unknown contact id.
- **Route wiring:** add `set_favourite` and `is_favourite` to the
  `from models import (...)` block in `routes/contacts.py`, and add
  `is_favourite=is_favourite(db, contact_id)` as a `render_template(...)` keyword
  argument in the existing `detail` view. (It is a template kwarg, not a local
  binding — do not write `is_favourite = is_favourite(...)`, which would shadow
  the imported helper.)

## 5. Display

- **List (`contacts.html`) — mind the wrapping form.** The results table is
  already inside one big `<form id="bulk-form">` (the bulk-delete / merge form,
  which opens before `<table>` and closes after `</table>`). HTML forbids nested
  `<form>` elements, so the per-row star toggle **must not** be a `<form>` inside
  the row. Use HTML5 form-association instead: render one
  `<form id="fav-{{ c.id }}" method="post" action="{{ url_for('contacts.toggle_favourite', contact_id=c.id) }}">`
  per contact **outside** `#bulk-form` — a second `{% for c in contacts %}` loop
  placed after its `</form>` but still inside the `{% if contacts %}` block — each
  carrying the hidden `_csrf_token`
  (`{{ csrf_token() }}`), the desired `favourite` value
  (`{{ 0 if c.is_favourite else 1 }}`), and a hidden `ref` =
  `request.full_path.rstrip('?')` — the same expression the row's detail link uses,
  here as a hidden-field value (Jinja-autoescaped; the browser re-encodes it on
  submit), so page/sort/filter args survive. In the row itself, place the
  `<button form="fav-{{ c.id }}" type="submit" class="fav-toggle">` inside the
  existing Name cell's `.name-cell` div (no new column, so the `<thead>` and
  column alignment are untouched) — the `form=` attribute binds the button to its
  out-of-table form even though the button sits inside `#bulk-form`. The button
  shows a filled star (★) when `c.is_favourite`, an outline star (☆) otherwise,
  with an `aria-label` of "Remove from favourites" / "Add to favourites". (This emits
  one tiny `<form>` per listed contact, up to `per_page` (≤200), after the table —
  harmless for a single-user localhost app.)
- **Detail (`contact_detail.html`):** a standalone star-toggle
  `<form method="post" action="{{ url_for('contacts.toggle_favourite', contact_id=contact.id) }}">`
  in the `.detail-header` beside the name / type badge — the detail page has no
  wrapping form (only a separate inline delete form), so nesting is not a concern
  here — carrying `_csrf_token`, the desired `favourite` value
  (`{{ 0 if is_favourite else 1 }}` — the detail template uses the `is_favourite`
  kwarg, not `c.is_favourite`), and its own `<button class="fav-toggle">`, but
  **no `ref`** (so the empty-ref branch round-trips to detail per §4). The `detail`
  view passes `is_favourite(db, contact_id)` so the template picks the ★/☆ glyph.
  *Accepted trade-off:* with no `ref`, after starring on a detail page the page's
  "Back to list" link reverts to the *unfiltered* list (the carried list filter is
  lost). Preserving it would mean threading the list ref through the toggle without
  triggering the route's list-redirect branch — not worth the complexity here;
  starring happens mainly from the list, where the `ref` *is* preserved.
- **CSS (`static/style.css`):** a small `.fav-toggle` rule for star colour and
  hover. The filled-vs-outline distinction is the glyph itself (★ vs ☆, chosen by
  a template `{% if c.is_favourite %}`), not CSS. No JavaScript — the toggle is a
  plain POST that reloads, consistent with the app's server-rendered, no-JS
  convention.

## 6. DESIGN.md amendments

Applied in the same change-set as the implementation:

- **§9 route table** (columns Method / Path / Description) — add a row: Method
  `POST`, Path `/contacts/<id>/favourite`, Description "Toggle favourite / pinned
  status". (That table already omits some shipped routes — e.g. `/contacts/birthdays`
  and the import / merge routes — a pre-existing gap unrelated to this change.)
- **§14 file-size budget** — note the additions; the shipped-`.py` total remains
  under the ~100 KB soft target. No dependency-budget change.

## 7. Testing

New tests (mirroring the existing `tests/` structure — `test_models.py`,
`test_routes.py`):

- **Migration/schema:** `contact_favourites` exists after init; re-init is a
  no-op (idempotent).
- **Model:** `set_favourite(True)` then `is_favourite` → True; `set_favourite(False)`
  → False; `set_favourite(True)` twice is idempotent (one row); deleting the
  contact cascades away the favourite row.
- **Ordering:** with a mix of starred/unstarred contacts, `list_contacts` returns
  all favourites before all non-favourites for **every** sort column and both
  directions; the favourite block is internally ordered by the chosen sort. Include
  a case where an active filter (e.g. `type`/`letter`) excludes a favourite — it
  must **not** appear (pinning is within the filtered set, per §3).
- **Total not inflated:** the `is_favourite` scalar does not change the returned
  `total` (the CL-0025 fan-out guard still holds).
- **Route:** `POST …/favourite` with `favourite=1` stars, `favourite=0` un-stars;
  unknown id → 404; missing CSRF → 403; a safe `ref` is honoured on redirect, an
  unsafe `ref` (`//host`) is rejected; no-`ref` redirects to detail.
- **Display:** the list renders a filled star for a favourite and an outline star
  otherwise; the detail page reflects the current state.

## 8. Out of scope

- **A "favourites-only" filter** (a toggle to show *only* starred contacts, like
  the type filter). Natural follow-up; not needed for the pin-to-top goal. Can be
  a later roadmap item if wanted.
- **Ordering favourites relative to each other** beyond the active sort (e.g.
  manual drag-to-reorder).
- **Syncing favourite status to Google.** The People API "starred" concept is not
  part of the basic sync surface; favourites stay local.

## 9. Invariants

| ID | Invariant | Test surface |
|----|-----------|--------------|
| INV-1 | A contact is a favourite iff exactly one row exists in `contact_favourites` for its id; `set_favourite` is idempotent in both directions. | `test_models.py` set/unset/double-set |
| INV-2 | Favourites sort strictly before non-favourites for every `sort`/`sort_dir`/filter combination; within each block the chosen sort applies. | `test_models.py` ordering across sorts + a filter that excludes a favourite |
| INV-3 | The `is_favourite` scalar `EXISTS` column never changes the list `total` (no row fan-out). | `test_models.py` total-unchanged |
| INV-4 | Deleting a contact removes its `contact_favourites` row (ON DELETE CASCADE). | `test_models.py` cascade |
| INV-5 | Favourite state changes only through the CSRF-validated `POST /contacts/<id>/favourite`; no GET path mutates it. | `test_routes.py` CSRF/404/method |
| INV-6 | The toggle redirect returns only to a local path (`_safe_ref`), never off-site. | `test_routes.py` safe/unsafe ref |
