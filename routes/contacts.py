from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

import phoneutil
import photos
from db import get_db
from models import (
    _normalize_tags,
    clear_contact_photo,
    create_contact,
    delete_contact,
    find_all_duplicates,
    find_duplicates,
    get_all_tags,
    get_contact,
    get_contact_photo_ext,
    get_contact_tags,
    get_custom_fields,
    get_edited_at,
    get_letter_counts,
    get_type_counts,
    is_favourite,
    list_contacts,
    set_contact_photo,
    set_favourite,
    update_contact,
    upcoming_birthdays,
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
    # CL-0037: repeated ?tag= params, normalized (dedup/clean) via the same
    # choke-point the write path uses.
    tags = _normalize_tags(', '.join(request.args.getlist('tag')))

    db = get_db()
    sort = request.args.get('sort') or s['sort']
    sort_dir = request.args.get('dir') or s['sort_dir']

    contacts, total = list_contacts(
        db, page, per_page, search or None, contact_type or None, letter or None,
        sort=sort, sort_dir=sort_dir, tags=tags or None,
    )
    # list_contacts already computed the total and clamped the page internally;
    # reuse both here instead of issuing a second COUNT (CL-0017).
    total_pages = max((total + per_page - 1) // per_page, 1)
    # When the list is unfiltered, `total` is the full contact count — seed the
    # nav-badge cache so the context processor skips its own COUNT (CL-0031). An
    # active tag filter is a filtered view, so it must not seed the badge (INV-7).
    if not (search or contact_type or letter or tags):
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
        all_tags=get_all_tags(db),
        active_tags=tags,
        active_tags_lc={t.lower() for t in tags},
    )


@bp.route('/contacts/duplicates')
def duplicates():
    """Scan all contacts and show duplicate names, emails, and phone numbers."""
    db = get_db()
    dupes = find_all_duplicates(db, g.settings['phone_region'])
    total = sum(len(groups) for groups in dupes.values())
    return render_template('duplicates.html', dupes=dupes, total=total)


@bp.route('/contacts/birthdays')
def birthdays():
    """Contacts whose 'birthday' custom field falls within the next N days (CL-0038)."""
    db = get_db()
    try:
        days = int(request.args.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    days = min(max(days, 1), 366)
    upcoming = upcoming_birthdays(db, within_days=days)
    return render_template('birthdays.html', upcoming=upcoming, days=days)


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
        ref=ref, default_type=g.settings['default_type'], tags_str='',
    )


def _apply_photo(db, contact_id: int) -> None:
    """Apply a photo upload or removal from the current request to a contact.

    Upload wins over remove: if a new file is present it is stored (ignoring
    remove_photo); otherwise a ticked remove_photo clears the photo. A bad
    upload flashes a friendly error but never blocks saving the contact.
    """
    file = request.files.get('photo')
    if file and file.filename:
        old_ext = get_contact_photo_ext(db, contact_id)
        # Read one byte past the cap so an oversize body is detectable without
        # buffering the whole stream; save_photo rejects len > MAX_PHOTO_BYTES.
        data = file.read(photos.MAX_PHOTO_BYTES + 1)
        try:
            ext = photos.save_photo(
                current_app.config, contact_id, data, old_ext=old_ext
            )
        except ValueError:
            flash('Photo must be a JPEG, PNG, GIF or WebP under 4 MB.', 'error')
        else:
            set_contact_photo(db, contact_id, ext)
    elif request.form.get('remove_photo'):
        old_ext = clear_contact_photo(db, contact_id)
        photos.delete_photo(current_app.config, contact_id, old_ext)


@bp.route('/contacts/<int:contact_id>/photo')
def photo(contact_id: int):
    db = get_db()
    ext = get_contact_photo_ext(db, contact_id)
    if not ext:
        abort(404)
    # Serve the 256 px thumbnail (CL-0035), lazily generating it from the
    # original if missing and falling back to the full-size original if it can't
    # be made. avatar_filename returns a basename built from the int id + our own
    # allow-listed ext (no request string), so send_from_directory still rejects
    # any escaping path and 404s a missing file. max_age lets browsers cache
    # avatars for a day instead of revalidating on every navigation; the
    # ETag/Last-Modified send_file sets still allow conditional revalidation once
    # the cache entry expires.
    filename = photos.avatar_filename(current_app.config, contact_id, ext)
    return send_from_directory(
        current_app.config['PHOTOS_DIR'],
        filename,
        mimetype=photos.mime_for_ext(ext),
        max_age=86400,
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
            tags_str=request.form.get('tags', ''),
        ), 400

    db = get_db()
    for warning in find_duplicates(
        db, fields['name'], fields['phone'], g.settings['phone_region']
    ):
        flash(f'Note: {warning}', 'error')

    contact_id = create_contact(
        db, fields['type'], fields['name'],
        fields['email'], fields['phone'], fields['notes'],
        custom_fields, _normalize_tags(request.form.get('tags', '')),
    )
    _apply_photo(db, contact_id)
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
    photo_ext = get_contact_photo_ext(db, contact_id)
    return render_template(
        'contact_detail.html', contact=contact, custom_fields=cfs,
        ref=ref, list_url=list_url, photo_ext=photo_ext,
        edited_at=get_edited_at(db, contact_id),
        is_favourite=is_favourite(db, contact_id),
        tags=get_contact_tags(db, contact_id),
    )


@bp.route('/contacts/<int:contact_id>/edit')
def edit(contact_id: int):
    db = get_db()
    contact = get_contact(db, contact_id)
    if not contact:
        abort(404)
    cfs = get_custom_fields(db, contact_id)
    ref = _safe_ref(_get_ref())
    photo_ext = get_contact_photo_ext(db, contact_id)
    return render_template(
        'contact_form.html', contact=contact, custom_fields=cfs, editing=True,
        ref=ref, photo_ext=photo_ext,
        tags_str=', '.join(get_contact_tags(db, contact_id)),
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
            tags_str=request.form.get('tags', ''),
        ), 400

    update_contact(
        db, contact_id, fields['type'], fields['name'],
        fields['email'], fields['phone'], fields['notes'],
        custom_fields, _normalize_tags(request.form.get('tags', '')),
    )
    _apply_photo(db, contact_id)
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
            old_ext = get_contact_photo_ext(db, cid_int)
            delete_contact(db, cid_int)
            photos.delete_photo(current_app.config, cid_int, old_ext)
            count += 1
    flash(f'Deleted {count} contact{"s" if count != 1 else ""}.', 'success')
    return redirect(redirect_to)


@bp.route('/contacts/<int:contact_id>/delete', methods=['POST'])
def delete(contact_id: int):
    db = get_db()
    contact = get_contact(db, contact_id)
    if not contact:
        abort(404)
    old_ext = get_contact_photo_ext(db, contact_id)
    delete_contact(db, contact_id)
    photos.delete_photo(current_app.config, contact_id, old_ext)
    ref = _safe_ref(_get_ref())
    if ref:
        return redirect(ref)
    return redirect(url_for('contacts.contact_list'))


@bp.route('/contacts/<int:contact_id>/favourite', methods=['POST'])
def toggle_favourite(contact_id: int):
    """Star / un-star a contact (CL-0039). Sets the posted desired end-state
    (`favourite=1` stars, anything else un-stars); returns to the carried list
    `ref` or, when none, back to the contact's detail page."""
    db = get_db()
    if not get_contact(db, contact_id):
        abort(404)
    set_favourite(db, contact_id, request.form.get('favourite') == '1')
    ref = _safe_ref(_get_ref())
    if ref:
        return redirect(ref)
    return redirect(url_for('contacts.detail', contact_id=contact_id))
