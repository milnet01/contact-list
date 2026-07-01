from __future__ import annotations

import csv
import io
import logging
import re
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

import importer
import phoneutil
import vcard
from db import get_db
from models import (
    create_contact,
    delete_contact,
    export_contacts,
    find_all_duplicates,
    find_duplicates,
    get_contact,
    get_custom_fields,
    get_import_profile,
    get_letter_counts,
    get_type_counts,
    import_contact,
    list_contacts,
    merge_contacts,
    sanitize_field_name,
    save_import_profile,
    update_contact,
    valid_field_name,
)

log = logging.getLogger(__name__)

bp = Blueprint('contacts', __name__)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_PHONE_RE = re.compile(r'^[\d\s\+\-\(\)\.]{3,30}$')


def _validate_custom_fields(form) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse and validate custom fields from the form. Returns (custom_fields, errors)."""
    cf_names = form.getlist('cf_name')
    cf_values = form.getlist('cf_value')
    custom_fields: list[tuple[str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for cn, cv in zip(cf_names, cf_values, strict=False):
        cn, cv = cn.strip(), cv.strip()
        if not (cn and cv):
            continue
        if not valid_field_name(cn):
            errors.append(
                f'Invalid field name: "{cn}" (letters, numbers, spaces, '
                'underscores only, max 64 chars).'
            )
        elif cn.lower() in seen:
            errors.append(f'Duplicate field name: "{cn}".')
        else:
            seen.add(cn.lower())
            custom_fields.append((cn, cv))
    if len(custom_fields) > 50:
        errors.append('Maximum 50 custom fields allowed.')
    return custom_fields, errors


def _validate_form(form) -> tuple[dict, list[tuple[str, str]], list[str]]:
    """Parse and validate the contact form. Returns (fields, custom_fields, errors)."""
    contact_type = form.get('type', '').strip()
    name = form.get('name', '').strip()
    email = form.get('email', '').strip() or None
    phone = form.get('phone', '').strip() or None
    notes = form.get('notes', '').strip() or None

    errors: list[str] = []

    if contact_type not in ('individual', 'company'):
        errors.append('Type must be individual or company.')
    if not name:
        errors.append('Name is required.')
    if email and not _EMAIL_RE.match(email):
        errors.append('Invalid email address.')
    if phone and not _PHONE_RE.match(phone):
        errors.append('Invalid phone number.')
    elif phone:
        phone = phoneutil.format_phone(phone, g.settings['phone_region'])

    custom_fields, cf_errors = _validate_custom_fields(form)
    errors.extend(cf_errors)

    fields = {
        'type': contact_type,
        'name': name,
        'email': email,
        'phone': phone,
        'notes': notes,
    }
    return fields, custom_fields, errors


@bp.route('/')
def index():
    return redirect(url_for('contacts.contact_list'))


@bp.route('/contacts')
def contact_list():
    s = g.settings
    page = max(request.args.get('page', 1, type=int), 1)

    per_page_arg = request.args.get('per_page', type=int)
    per_page = per_page_arg if per_page_arg is not None else int(s['per_page'])
    per_page = max(1, min(per_page, 200))

    search = request.args.get('q', '').strip()
    contact_type = request.args.get('type', '').strip()
    letter = request.args.get('letter', '').strip()

    db = get_db()
    sort = request.args.get('sort') or s['sort']
    sort_dir = request.args.get('dir') or s['sort_dir']

    contacts, total = list_contacts(
        db, page, per_page, search or None, contact_type or None, letter or None,
        sort=sort, sort_dir=sort_dir,
    )
    # list_contacts already computed the total and clamped the page internally;
    # reuse both here instead of issuing a second COUNT (CL-0017).
    total_pages = max((total + per_page - 1) // per_page, 1)
    # When the list is unfiltered, `total` is the full contact count — seed the
    # nav-badge cache so the context processor skips its own COUNT (CL-0031).
    if not (search or contact_type or letter):
        g.contact_count = total
    page = min(max(page, 1), total_pages)
    letter_counts = get_letter_counts(db)
    type_counts = get_type_counts(db)

    return render_template(
        'contacts.html',
        contacts=contacts,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        search=search,
        contact_type=contact_type,
        letter=letter,
        letter_counts=letter_counts,
        sort=sort,
        sort_dir=sort_dir,
        type_counts=type_counts,
    )


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


@bp.route('/contacts/duplicates')
def duplicates():
    """Scan all contacts and show duplicate names, emails, and phone numbers."""
    db = get_db()
    dupes = find_all_duplicates(db, g.settings['phone_region'])
    total = sum(len(groups) for groups in dupes.values())
    return render_template('duplicates.html', dupes=dupes, total=total)


def _get_ref() -> str:
    """Get the list page URL carried through the navigation chain."""
    return request.args.get('ref', '') or request.form.get('ref', '')


def _safe_ref(ref: str) -> str:
    """Only allow local paths as return targets.

    Rejects protocol-relative URLs (``//host``) and the backslash variant
    (``/\\host``) that browsers normalise to ``//host`` — both would otherwise
    redirect off-site. Also rejects any control character (CR/LF etc.) so the
    value can never carry a header-splitting payload.
    """
    if (
        ref.startswith('/')
        and not ref.startswith('//')
        and '\\' not in ref
        and ref.isprintable()
    ):
        return ref
    return ''


@bp.route('/contacts/new')
def new_contact():
    ref = _safe_ref(_get_ref())
    return render_template(
        'contact_form.html', contact=None, custom_fields=[], editing=False,
        ref=ref, default_type=g.settings['default_type'],
    )


@bp.route('/contacts', methods=['POST'])
def create():
    ref = _safe_ref(_get_ref())
    fields, custom_fields, errors = _validate_form(request.form)

    if errors:
        return render_template(
            'contact_form.html',
            contact=fields,
            custom_fields=[
                {'field_name': cn, 'field_value': cv} for cn, cv in custom_fields
            ],
            editing=False,
            errors=errors,
            ref=ref,
        ), 400

    db = get_db()
    for warning in find_duplicates(
        db, fields['name'], fields['phone'], g.settings['phone_region']
    ):
        flash(f'Note: {warning}', 'error')

    contact_id = create_contact(
        db, fields['type'], fields['name'],
        fields['email'], fields['phone'], fields['notes'],
        custom_fields,
    )
    return redirect(url_for('contacts.detail', contact_id=contact_id, ref=ref))


@bp.route('/contacts/<int:contact_id>')
def detail(contact_id: int):
    db = get_db()
    contact = get_contact(db, contact_id)
    if not contact:
        abort(404)
    cfs = get_custom_fields(db, contact_id)
    # Carry ref from query param, or capture from referrer if arriving from list
    ref = _safe_ref(_get_ref())
    if not ref:
        referrer = request.referrer or ''
        parsed = urlparse(referrer)
        if parsed.path == '/contacts' and parsed.query:
            ref = f'{parsed.path}?{parsed.query}'
    list_url = ref or url_for('contacts.contact_list')
    return render_template(
        'contact_detail.html', contact=contact, custom_fields=cfs,
        ref=ref, list_url=list_url,
    )


@bp.route('/contacts/<int:contact_id>/edit')
def edit(contact_id: int):
    db = get_db()
    contact = get_contact(db, contact_id)
    if not contact:
        abort(404)
    cfs = get_custom_fields(db, contact_id)
    ref = _safe_ref(_get_ref())
    return render_template(
        'contact_form.html', contact=contact, custom_fields=cfs, editing=True, ref=ref
    )


@bp.route('/contacts/<int:contact_id>', methods=['POST'])
def update(contact_id: int):
    db = get_db()
    contact = get_contact(db, contact_id)
    if not contact:
        abort(404)

    ref = _safe_ref(_get_ref())
    fields, custom_fields, errors = _validate_form(request.form)

    if errors:
        return render_template(
            'contact_form.html',
            contact={**fields, 'id': contact_id},
            custom_fields=[
                {'field_name': cn, 'field_value': cv} for cn, cv in custom_fields
            ],
            editing=True,
            errors=errors,
            ref=ref,
        ), 400

    update_contact(
        db, contact_id, fields['type'], fields['name'],
        fields['email'], fields['phone'], fields['notes'],
        custom_fields,
    )
    return redirect(url_for('contacts.detail', contact_id=contact_id, ref=ref))


@bp.route('/contacts/bulk-delete', methods=['POST'])
def bulk_delete():
    ids = request.form.getlist('selected')
    ref = _safe_ref(request.form.get('ref', ''))
    redirect_to = ref or url_for('contacts.contact_list')
    if not ids:
        flash('No contacts selected.', 'error')
        return redirect(redirect_to)
    db = get_db()
    count = 0
    for cid in ids:
        try:
            cid_int = int(cid)
        except ValueError:
            continue
        if get_contact(db, cid_int):
            delete_contact(db, cid_int)
            count += 1
    flash(f'Deleted {count} contact{"s" if count != 1 else ""}.', 'success')
    return redirect(redirect_to)


@bp.route('/contacts/<int:contact_id>/delete', methods=['POST'])
def delete(contact_id: int):
    db = get_db()
    contact = get_contact(db, contact_id)
    if not contact:
        abort(404)
    delete_contact(db, contact_id)
    ref = _safe_ref(_get_ref())
    if ref:
        return redirect(ref)
    return redirect(url_for('contacts.contact_list'))


# --- Import / export / merge (CL-0022, CL-0023, CL-0024) --------------------


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

    return render_template(
        'merge.html', contacts=contacts, survivor_id=survivor_id,
        loser_ids=loser_ids, core=core, customs=list(union.values()),
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

    try:
        merge_contacts(db, survivor_id, loser_ids, fields, customs)
    except ValueError as exc:
        flash(f'Could not merge: {exc}', 'error')
        return redirect(url_for('contacts.duplicates'))

    flash(f'Merged {len(loser_ids) + 1} contacts into one.', 'success')
    return redirect(url_for('contacts.detail', contact_id=survivor_id))
