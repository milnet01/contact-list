"""CSV / vCard import and export routes (CL-0022, CL-0023).

These views attach to the shared ``contacts`` blueprint defined in
``routes.contacts`` so their endpoint names (``contacts.export``,
``contacts.import_view`` …) and URLs are unchanged — this module is a pure
organisational split of routes/contacts.py, not a new blueprint (CL-0036).
"""
from __future__ import annotations

import csv
import io
import re

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
            _csv_safe(c['name']), _csv_safe(c['type']), _csv_safe(c['email']),
            _csv_safe(c['phone']), _csv_safe(c['notes']),
            c['created_at'], c['updated_at'],
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=contacts.csv'},
    )


# Leading characters a spreadsheet treats as the start of a formula. A contact
# field beginning with one of these executes when the exported CSV is opened in
# Excel or LibreOffice (OWASP CSV injection / CWE-1236). The contact data is not
# ours -- it arrives from an imported file or a Google sync pull -- so this is a
# trust boundary on the way OUT, which DESIGN.md §6.1 (input handling) does not
# cover.
_CSV_FORMULA_LEADERS = ('=', '@', '\t', '\r')
# `+` and `-` lead a formula too, but they also lead every E.164 phone number
# (phoneutil.normalize_e164 always emits one) and every negative number. Quoting
# those would mangle the most common field in the export, so they are escaped
# only when what follows is not phone- or number-shaped.
_CSV_AMBIGUOUS_LEADERS = ('+', '-')
_CSV_NUMERIC_TAIL = re.compile(r'^[0-9\s()+.\-]*$')


def _csv_safe(value: object) -> str:
    """Neutralise a spreadsheet formula leader on one exported CSV field.

    Prefixes a single quote, which every major spreadsheet reads as "treat the
    rest as text". Non-destructive for every value that does not start with a
    formula character -- including international phone numbers, which is why the
    `+`/`-` case is narrowed rather than blanket-quoted.
    """
    text = '' if value is None else str(value)
    if text.startswith(_CSV_FORMULA_LEADERS):
        return "'" + text
    if text.startswith(_CSV_AMBIGUOUS_LEADERS) and not _CSV_NUMERIC_TAIL.match(text[1:]):
        return "'" + text
    return text


def _count_vcard_blocks(text: str) -> int:
    """Count BEGIN:VCARD markers, so a card the parser dropped can be reported.

    vcard.parse returns only cards it could finalise; the difference between
    this count and len(parse(...)) is the number silently discarded.
    """
    return sum(
        1 for line in text.splitlines()
        if line.strip().upper().startswith('BEGIN:VCARD')
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
    created = updated = skipped = 0
    warnings: list[str] = []
    updated_names: list[str] = []

    # vcard.parse drops any card with no usable name, and those are skips the
    # user is entitled to hear about. Counting them here means the summary
    # covers both loss paths -- the ones the parser rejected and the ones
    # import_contact refuses below.
    unusable = _count_vcard_blocks(text) - len(cards)
    if unusable > 0:
        skipped += unusable
        warnings.append(
            f'{unusable} card(s) had no usable name and were skipped.'
        )
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
        except ValueError as exc:
            # Was `continue` with a hardcoded skipped=0 in the summary below, so
            # a 200-card file where 150 were refused rendered as an unqualified
            # "50 created". The CSV path a few functions down already counted
            # and reported these; this is the same accounting.
            skipped += 1
            warnings.append(f'{card["name"] or "(unnamed)"}: {exc}')
            continue
        if action == 'created':
            created += 1
        else:
            updated += 1
            updated_names.append(card['name'])
    return render_template(
        'import.html', stage='summary', created=created, updated=updated,
        updated_names=updated_names, skipped=skipped, warnings=warnings,
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
