"""CSV / vCard import and export routes (CL-0022, CL-0023).

These views attach to the shared ``contacts`` blueprint defined in
``routes.contacts`` so their endpoint names (``contacts.export``,
``contacts.import_view`` …) and URLs are unchanged — this module is a pure
organisational split of routes/contacts.py, not a new blueprint (CL-0036).
"""
from __future__ import annotations

import csv
import io

from flask import (
    Response,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

import importer
import vcard
from db import get_db
from models import (
    export_contacts,
    get_custom_fields,
    get_import_profile,
    import_contact,
    sanitize_field_name,
    save_import_profile,
)
from routes.contacts import bp


@bp.route('/contacts/export')
def export():
    """Export all contacts as a CSV download."""
    db = get_db()
    contacts = export_contacts(db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Type', 'Email', 'Phone', 'Notes', 'Created', 'Updated'])
    for c in contacts:
        writer.writerow([
            c['name'], c['type'], c['email'] or '', c['phone'] or '',
            c['notes'] or '', c['created_at'], c['updated_at'],
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=contacts.csv'},
    )


def _import_vcard_text(text: str):
    """Import a vCard document immediately (no mapping needed) and show the
    summary. Additive import (import_contact) is non-destructive, so there is
    nothing to preview-gate."""
    cards = vcard.parse(text)
    if not cards:
        flash('No contacts found in the file.', 'error')
        return redirect(url_for('contacts.import_view'))
    db = get_db()
    created = updated = 0
    updated_names: list[str] = []
    for card in cards:
        # Sanitise externally-supplied custom-field names and drop within-card
        # duplicates so one odd label can't fail the whole contact's import.
        seen: set[str] = set()
        cfs: list[tuple[str, str]] = []
        for name, value in card['custom_fields']:
            clean = sanitize_field_name(name)
            if not clean or not value or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            cfs.append((clean, value))
        fields = {
            'type': card['type'], 'name': card['name'], 'email': card['email'],
            'phone': card['phone'], 'notes': card['notes'],
        }
        try:
            _cid, action = import_contact(db, fields, cfs)
        except ValueError:
            continue
        if action == 'created':
            created += 1
        else:
            updated += 1
            updated_names.append(card['name'])
    return render_template(
        'import.html', stage='summary', created=created, updated=updated,
        updated_names=updated_names, skipped=0, warnings=[],
    )


@bp.route('/contacts/import', methods=['GET', 'POST'])
def import_view():
    if request.method == 'GET':
        return render_template('import.html', stage='upload')

    file = request.files.get('file')
    if file is None or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('contacts.import_view'))

    raw = file.read()
    if len(raw) > current_app.config.get('MAX_IMPORT_BYTES', 1024 * 1024):
        flash('That file is too large to import (limit 1 MB).', 'error')
        return redirect(url_for('contacts.import_view'))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        flash('Could not read file — please save it as UTF-8.', 'error')
        return redirect(url_for('contacts.import_view'))

    if file.filename.lower().endswith('.vcf') or text.lstrip().upper().startswith('BEGIN:VCARD'):
        return _import_vcard_text(text)

    try:
        headers, rows = importer.parse_csv(text)
    except csv.Error:
        flash('Could not parse that CSV file.', 'error')
        return redirect(url_for('contacts.import_view'))
    if not headers:
        flash('That file has no columns to import.', 'error')
        return redirect(url_for('contacts.import_view'))

    mapping = importer.guess_mapping(headers)
    db = get_db()
    profile = get_import_profile(db, importer.header_signature(headers))
    if profile:
        for i, h in enumerate(headers):
            if h in profile['mapping']:
                mapping[i] = profile['mapping'][h]
        default_type = profile['default_type']
    else:
        default_type = g.settings['default_type']

    return render_template(
        'import.html', stage='map', headers=headers, mapping=mapping,
        preview=rows[:5], csv_text=text, targets=importer.TARGETS,
        default_type=default_type,
    )


@bp.route('/contacts/import/apply', methods=['POST'])
def import_apply():
    csv_text = request.form.get('csv_text', '')
    default_type = request.form.get('default_type', 'individual')
    if default_type not in ('individual', 'company'):
        default_type = 'individual'
    try:
        headers, rows = importer.parse_csv(csv_text)
    except csv.Error:
        flash('Could not parse the CSV.', 'error')
        return redirect(url_for('contacts.import_view'))
    if not headers:
        flash('Nothing to import.', 'error')
        return redirect(url_for('contacts.import_view'))

    mapping: dict[int, str] = {}
    for i in range(len(headers)):
        target = request.form.get(f'map_{i}', 'ignore')
        mapping[i] = target if target in importer.TARGETS else 'ignore'

    built, skipped = importer.apply_mapping(headers, rows, mapping, default_type)
    db = get_db()
    created = updated = 0
    updated_names: list[str] = []
    warnings: list[str] = []
    for fields, cfs in built:
        try:
            _cid, action = import_contact(db, fields, cfs)
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        if action == 'created':
            created += 1
        else:
            updated += 1
            updated_names.append(fields['name'])

    save_import_profile(
        db, importer.header_signature(headers),
        {headers[i]: mapping[i] for i in range(len(headers))}, default_type,
    )
    return render_template(
        'import.html', stage='summary', created=created, updated=updated,
        updated_names=updated_names, skipped=skipped, warnings=warnings,
    )


@bp.route('/contacts/export/vcard')
def export_vcard():
    """Export all contacts (with their custom fields) as a vCard download."""
    db = get_db()
    contacts = []
    for r in export_contacts(db):
        contacts.append({
            'type': r['type'], 'name': r['name'], 'email': r['email'],
            'phone': r['phone'], 'notes': r['notes'],
            'custom_fields': [
                (cf['field_name'], cf['field_value'])
                for cf in get_custom_fields(db, r['id'])
            ],
        })
    return Response(
        vcard.emit(contacts),
        mimetype='text/vcard',
        headers={'Content-Disposition': 'attachment; filename=contacts.vcf'},
    )
