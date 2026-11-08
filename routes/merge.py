"""Contact merge routes (CL-0024).

These views attach to the shared ``contacts`` blueprint defined in
``routes.contacts`` so their endpoint names (``contacts.merge_preview``,
``contacts.merge_apply``) and URLs are unchanged — this module is a pure
organisational split of routes/contacts.py, not a new blueprint (CL-0036).
"""
from __future__ import annotations

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

import photos
from config import VALID_CONTACT_TYPES
from db import get_db
from models import (
    MAX_CUSTOM_FIELDS,
    _normalize_tags,
    get_contact,
    get_contact_photo_ext,
    get_contact_tags,
    get_custom_fields,
    merge_contacts,
)
from routes.contacts import _safe_ref, bp, selected_ids, validate_core_fields


def _preserve_extra(
    involved: list, key: str, kind: str, chosen: str | None,
    customs: list[tuple[str, str]], used: set[str],
) -> None:
    """Keep every distinct ``key`` value of the merged contacts that was not
    chosen, as a numbered custom field ('Email 2', ...), so a merge never drops
    a unique email or phone (the import's "extras become custom fields" rule).

    Appends to ``customs`` and adds each new label to ``used`` (lower-case names
    already taken). Run it before merge_contacts deletes the losers, while
    ``involved`` still holds their values.
    """
    kept = {chosen.strip().lower()} if chosen else set()
    for c in involved:
        value = (c[key] or '').strip()
        if not value or value.lower() in kept:
            continue
        kept.add(value.lower())
        n = 2
        label = f'{kind} {n}'
        while label.lower() in used:
            n += 1
            label = f'{kind} {n}'
        used.add(label.lower())
        customs.append((label, value))


def _too_many_fields(count: int, extras: bool = False) -> str:
    """The message refusing a merge whose contact would pass MAX_CUSTOM_FIELDS.
    A merge is refused rather than trimmed, so no field is lost (CL-0118)."""
    why = ', counting the extra emails and phones kept as fields,' if extras else ''
    return (
        f'These contacts would have {count} custom fields{why} and a contact '
        f'can hold at most {MAX_CUSTOM_FIELDS}. Remove some fields from one of '
        'them, then merge again.'
    )


@bp.route('/contacts/merge', methods=['POST'])
def merge_preview() -> ResponseReturnValue:
    ids = selected_ids(request.form.getlist('selected'))

    back = _safe_ref(request.form.get('ref', '')) or url_for('contacts.contact_list')
    db = get_db()
    contacts = [c for c in (get_contact(db, i) for i in ids) if c]
    if len(contacts) < 2:
        flash('Select at least two contacts to merge.', 'error')
        return redirect(back)

    # The lowest id (the oldest contact) survives and keeps its own photo. The
    # choice ignores Google links: merge_contacts takes any survivor.
    survivor_id = min(c['id'] for c in contacts)
    loser_ids = [c['id'] for c in contacts if c['id'] != survivor_id]
    # Merge never deletes on Google (two-way sync spec INV-4), so the page
    # names each removed contact whose Google copy will stay (CL-0123).
    google_losers = [
        c['name'] for c in contacts
        if c['id'] != survivor_id and c['google_id']
    ]

    def distinct(key: str) -> list[str]:
        seen: list[str] = []
        for c in contacts:
            v = c[key]
            if v and v not in seen:
                seen.append(v)
        return seen

    core = {k: distinct(k) for k in ('name', 'type', 'email', 'phone', 'notes')}

    union: dict[str, dict] = {}
    for c in contacts:
        for cf in get_custom_fields(db, c['id']):
            entry = union.setdefault(
                cf['field_name'].lower(), {'name': cf['field_name'], 'values': []}
            )
            if cf['field_value'] not in entry['values']:
                entry['values'].append(cf['field_value'])
    if len(union) > MAX_CUSTOM_FIELDS:
        flash(_too_many_fields(len(union)), 'error')
        return redirect(back)

    # CL-0037: pre-fill the merge form's tags field with the union of every
    # involved contact's tags, so the survivor keeps them all by default (the
    # user can prune before confirming). `tag_union`, not `union` — the latter is
    # already bound above for the custom-field aggregation.
    tag_union = _normalize_tags(
        ', '.join(name for c in contacts for name in get_contact_tags(db, c['id']))
    )

    return render_template(
        'merge.html', contacts=contacts, survivor_id=survivor_id,
        loser_ids=loser_ids, core=core, customs=list(union.values()),
        tags_str=', '.join(tag_union), back=back, google_losers=google_losers,
    )


@bp.route('/contacts/merge/apply', methods=['POST'])
def merge_apply() -> ResponseReturnValue:
    db = get_db()
    # Every refusal returns to the page the merge started from (CL-0120).
    back = _safe_ref(request.form.get('ref', '')) or url_for('contacts.duplicates')
    try:
        survivor_id = int(request.form['survivor_id'])
        loser_ids = [int(x) for x in request.form.getlist('loser_id')]
    except (KeyError, ValueError):
        flash('Invalid merge request.', 'error')
        return redirect(back)

    # An unknown type falls back to individual rather than failing the merge:
    # the field is a <select>, so only a tampered request sends anything else.
    ctype = request.form.get('field_type')
    raw_email = (request.form.get('field_email') or '').strip() or None
    raw_phone = (request.form.get('field_phone') or '').strip() or None
    fields, errors = validate_core_fields(
        ctype if ctype in VALID_CONTACT_TYPES else 'individual',
        (request.form.get('field_name') or '').strip(),
        raw_email,
        raw_phone,
        (request.form.get('field_notes') or '').strip() or None,
    )
    if errors:
        for error in errors:
            flash(error, 'error')
        return redirect(back)

    try:
        cf_count = max(int(request.form.get('cf_count', 0)), 0)
    except ValueError:
        cf_count = 0
    # This is a loop bound taken straight from the request body, so an unbounded
    # value spun a worker thread for as long as the caller liked (CL-0067). Past
    # the cap it is refused, not clamped: a clamp dropped the later fields
    # without a word (CL-0118). The cap is the model's, so merge and the contact
    # form agree on how many custom fields a contact may carry.
    if cf_count > MAX_CUSTOM_FIELDS:
        flash(_too_many_fields(cf_count), 'error')
        return redirect(back)
    customs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i in range(cf_count):
        name = (request.form.get(f'cf_name_{i}') or '').strip()
        value = (request.form.get(f'cf_value_{i}') or '').strip()
        if name and value and name.lower() not in seen:
            seen.add(name.lower())
            customs.append((name, value))

    # Gather the values to preserve before merge_contacts deletes the losers.
    involved = [c for c in (get_contact(db, i) for i in [survivor_id, *loser_ids]) if c]
    used = {n.lower() for n, _ in customs}

    # Compare against the values as submitted: the chosen phone is now in
    # international form, and the other contacts still hold the raw one.
    _preserve_extra(involved, 'email', 'Email', raw_email, customs, used)
    _preserve_extra(involved, 'phone', 'Phone', raw_phone, customs, used)
    if len(customs) > MAX_CUSTOM_FIELDS:
        flash(_too_many_fields(len(customs), extras=True), 'error')
        return redirect(back)

    # Read loser photo exts before the merge deletes their rows, so we can
    # unlink the orphaned files afterwards (the survivor keeps its own photo).
    loser_photo_exts = {lid: get_contact_photo_ext(db, lid) for lid in loser_ids}

    tags = _normalize_tags(request.form.get('tags', ''))
    try:
        merge_contacts(db, survivor_id, loser_ids, fields, customs, tags)
    except ValueError as exc:
        flash(f'Could not merge: {exc}', 'error')
        return redirect(back)

    for lid, lext in loser_photo_exts.items():
        photos.delete_photo(current_app.config, lid, lext)

    flash(f'Merged {len(loser_ids) + 1} contacts into one.', 'success')
    return redirect(url_for('contacts.detail', contact_id=survivor_id))
