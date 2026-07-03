# Favourite / Pinned Contacts — Design (CL-0039)

Status: **Draft** — pending user review + `/cold-eyes` (not yet implemented).
Date: 2026-07-03

> **Decisions made autonomously while the user was away (2026-07-03) — please
> confirm or redirect during review:**
> 1. **Sort behaviour = "always pinned to top"** (§3): favourites form a block at
>    the top of the list, sorted among themselves by whatever sort is active;
>    everyone else follows. This matches the roadmap's "sort favourites first".
> 2. **Schema = a `contact_favourites` companion table** (§2), not a boolean
>    column on `contacts` — this follows the project's own idempotent-migration
>    pattern (005_photos, 006_contact_edits), since SQLite has no
>    `ADD COLUMN IF NOT EXISTS`.
> 3. **No "favourites-only" filter** in this scope (YAGNI — pinning already
>    surfaces them). Listed in §8 (Out of scope) as a future option.

Amends **DESIGN.md** in the same change-set as the implementation:
- **§9** (route table) — adds one route: `POST /contacts/<id>/favourite`.
- **§14** (file-size budget) — one new ~0.3 KB migration plus ~20 LOC of
  model/route and a small template/CSS addition; the shipped-`.py` total stays
  well under the ~100 KB soft budget. No new dependency (§3 unchanged).

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
delete keeps it in lockstep with the contact.

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
def set_favourite(db, contact_id: int, favourite: bool) -> None:
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

def is_favourite(db, contact_id: int) -> bool:
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

Favourites are **always pinned to the top**, regardless of the active sort
column, sort direction, or search/type/letter filter. Within the favourites
block and within the non-favourites block, the user's chosen sort applies as
normal.

Implementation: `_build_contact_query` gains one scalar column (same
non-fan-out `EXISTS` pattern as `has_photo`/`edited_at`, so it does **not**
inflate the `COUNT(*)`-over-subquery total):

```sql
EXISTS (SELECT 1 FROM contact_favourites f WHERE f.contact_id = contacts.id)
    AS is_favourite
```

and `list_contacts` prepends it to the ORDER BY:

```python
query += f' ORDER BY is_favourite DESC, {order_col} {direction}'
```

`is_favourite` is emitted as a column on every list row, so the template can
render the correct star state without a second query.

## 4. Toggle route

One route in `routes/contacts.py` (core CRUD module):

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

- **CSRF:** POST-only; the app's existing `before_request` CSRF guard validates
  the signed token on every POST, so a missing/invalid token is rejected (403)
  before the handler runs. The form carries the hidden `csrf_token`.
- **Desired-state form field:** the button posts `favourite=1` when the contact
  is not yet a favourite, `favourite=0` when it is (the template knows the
  current state from `is_favourite`). Anything other than `'1'` un-stars.
- **Return target:** reuses `_safe_ref`/`_get_ref` (local-paths-only) so starring
  a contact on list page 3 returns to page 3 with its filters intact; from the
  detail page (no `ref`) it redirects back to detail.
- **404** on an unknown contact id.

## 5. Display

- **List (`contacts.html`):** each row gets a small star-toggle `<form method="post">`
  posting to `contacts.toggle_favourite`, carrying `csrf_token`, the desired
  `favourite` value, and a hidden `ref` = the current list URL. The button shows
  a filled star (★) when `contact['is_favourite']`, an outline star (☆) otherwise,
  with an `aria-label` of "Remove from favourites" / "Add to favourites".
- **Detail (`contact_detail.html`):** the same toggle form near the contact name;
  state from `is_favourite(db, contact_id)` passed by the `detail` view.
- **CSS (`static/style.css`):** a small `.fav-toggle` rule (star colour, hover,
  filled vs outline). No JavaScript — the toggle is a plain POST that reloads,
  consistent with the app's server-rendered, no-JS convention.

## 6. DESIGN.md amendments (applied in the implementation change-set)

- **§9 route table** — add `POST /contacts/<id>/favourite → toggle_favourite`.
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
  directions; the favourite block is internally ordered by the chosen sort.
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
| INV-2 | Favourites sort strictly before non-favourites for every `sort`/`sort_dir`/filter combination; within each block the chosen sort applies. | `test_models.py` ordering across sorts |
| INV-3 | The `is_favourite` scalar subquery never changes the list `total` (no row fan-out). | `test_models.py` total-unchanged |
| INV-4 | Deleting a contact removes its `contact_favourites` row (ON DELETE CASCADE). | `test_models.py` cascade |
| INV-5 | Favourite state changes only through the CSRF-validated `POST /contacts/<id>/favourite`; no GET path mutates it. | `test_routes.py` CSRF/404/method |
| INV-6 | The toggle redirect returns only to a local path (`_safe_ref`), never off-site. | `test_routes.py` safe/unsafe ref |
