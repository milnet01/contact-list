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

import photos
from db import get_db
from models import (
    _normalize_tags,
    get_contact,
    get_contact_photo_ext,
    get_contact_tags,
    get_custom_fields,
    merge_contacts,
)
from routes.contacts import _safe_ref, bp


@bp.route('/contacts/merge', methods=['POST'])
def merge_preview():
    ids: list[int] = []
    for s in request.form.getlist('selected'):
        try:
            ids.append(int(s))
        except ValueError:
            continue
    ids = list(dict.fromkeys(ids))

    back = _safe_ref(request.form.get('ref', '')) or url_for('contacts.contact_list')
    db = get_db()
    contacts = [c for c in (get_contact(db, i) for i in ids) if c]
    if len(contacts) < 2:
        flash('Select at least two contacts to merge.', 'error')
        return redirect(back)

    survivor_id = min(c['id'] for c in contacts)
    loser_ids = [c['id'] for c in contacts if c['id'] != survivor_id]

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
        tags_str=', '.join(tag_union),
    )


@bp.route('/contacts/merge/apply', methods=['POST'])
def merge_apply():
    db = get_db()
    try:
        survivor_id = int(request.form['survivor_id'])
        loser_ids = [int(x) for x in request.form.getlist('loser_id')]
    except (KeyError, ValueError):
        flash('Invalid merge request.', 'error')
        return redirect(url_for('contacts.duplicates'))

    ctype = request.form.get('field_type')
    fields = {
        'type': ctype if ctype in ('individual', 'company') else 'individual',
        'name': (request.form.get('field_name') or '').strip(),
        'email': (request.form.get('field_email') or '').strip() or None,
        'phone': (request.form.get('field_phone') or '').strip() or None,
        'notes': (request.form.get('field_notes') or '').strip() or None,
    }
    if not fields['name']:
        flash('The merged contact needs a name.', 'error')
        return redirect(url_for('contacts.duplicates'))

    try:
        cf_count = int(request.form.get('cf_count', 0))
    except ValueError:
        cf_count = 0
    customs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i in range(cf_count):
        name = (request.form.get(f'cf_name_{i}') or '').strip()
        value = (request.form.get(f'cf_value_{i}') or '').strip()
        if name and value and name.lower() not in seen:
            seen.add(name.lower())
            customs.append((name, value))

    # Preserve non-chosen single-value fields as numbered custom fields so a
    # merge never silently drops a unique email/phone (matches import's "extras
    # become custom fields" rule). Gather before merge_contacts deletes losers.
    involved = [c for c in (get_contact(db, i) for i in [survivor_id, *loser_ids]) if c]
    used = {n.lower() for n, _ in customs}

    def _preserve_extra(key: str, kind: str, chosen: str | None) -> None:
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

    _preserve_extra('email', 'Email', fields['email'])
    _preserve_extra('phone', 'Phone', fields['phone'])

    # Read loser photo exts before the merge deletes their rows, so we can
    # unlink the orphaned files afterwards (the survivor keeps its own photo).
    loser_photo_exts = {lid: get_contact_photo_ext(db, lid) for lid in loser_ids}

    tags = _normalize_tags(request.form.get('tags', ''))
    try:
        merge_contacts(db, survivor_id, loser_ids, fields, customs, tags)
    except ValueError as exc:
        flash(f'Could not merge: {exc}', 'error')
        return redirect(url_for('contacts.duplicates'))

    for lid, lext in loser_photo_exts.items():
        photos.delete_photo(current_app.config, lid, lext)

    flash(f'Merged {len(loser_ids) + 1} contacts into one.', 'success')
    return redirect(url_for('contacts.detail', contact_id=survivor_id))
