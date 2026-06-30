from __future__ import annotations

import csv
import io
import logging
import re
from urllib.parse import urlparse

import phonenumbers
from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

log = logging.getLogger(__name__)

from db import get_db
from models import (
    count_contacts,
    create_contact,
    delete_contact,
    export_contacts,
    find_all_duplicates,
    find_duplicates,
    get_contact,
    get_custom_fields,
    get_letter_counts,
    list_contacts,
    update_contact,
    valid_field_name,
)

bp = Blueprint('contacts', __name__)

DEFAULT_REGION = 'ZA'
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_PHONE_RE = re.compile(r'^[\d\s\+\-\(\)\.]{3,30}$')


def format_phone(raw: str) -> str:
    """Parse and format a phone number to international format. Returns raw if unparseable."""
    try:
        parsed = phonenumbers.parse(raw, DEFAULT_REGION)
        if phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except phonenumbers.NumberParseException:
        pass
    return raw


def _validate_custom_fields(form) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse and validate custom fields from the form. Returns (custom_fields, errors)."""
    cf_names = form.getlist('cf_name')
    cf_values = form.getlist('cf_value')
    custom_fields: list[tuple[str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for cn, cv in zip(cf_names, cf_values):
        cn, cv = cn.strip(), cv.strip()
        if not (cn and cv):
            continue
        if not valid_field_name(cn):
            errors.append(f'Invalid field name: "{cn}" (letters, numbers, spaces, underscores only, max 64 chars).')
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
        phone = format_phone(phone)

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
    page = max(request.args.get('page', 1, type=int), 1)
    per_page = max(request.args.get('per_page', 50, type=int), 1)
    per_page = min(per_page, 200)
    search = request.args.get('q', '').strip()
    contact_type = request.args.get('type', '').strip()
    letter = request.args.get('letter', '').strip()

    db = get_db()
    sort = request.args.get('sort', 'name').strip()
    sort_dir = request.args.get('dir', 'asc').strip()

    total = count_contacts(db, search or None, contact_type or None, letter or None)
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)

    contacts, _ = list_contacts(
        db, page, per_page, search or None, contact_type or None, letter or None,
        sort=sort, sort_dir=sort_dir,
    )
    letter_counts = get_letter_counts(db)

    # Type breakdown for stats
    type_counts = {}
    for row in db.execute(
        'SELECT type, COUNT(*) AS cnt FROM contacts GROUP BY type'
    ).fetchall():
        type_counts[row['type']] = row['cnt']

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
    dupes = find_all_duplicates(db)
    total = sum(len(groups) for groups in dupes.values())
    return render_template('duplicates.html', dupes=dupes, total=total)


def _get_ref() -> str:
    """Get the list page URL carried through the navigation chain."""
    return request.args.get('ref', '') or request.form.get('ref', '')


def _safe_ref(ref: str) -> str:
    """Only allow local paths as return targets (reject protocol-relative URLs)."""
    return ref if ref.startswith('/') and not ref.startswith('//') else ''


@bp.route('/contacts/new')
def new_contact():
    ref = _safe_ref(_get_ref())
    return render_template(
        'contact_form.html', contact=None, custom_fields=[], editing=False, ref=ref
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
    for warning in find_duplicates(db, fields['name'], fields['phone']):
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
