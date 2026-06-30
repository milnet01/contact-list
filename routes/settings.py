from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

import settings as settings_mod
from db import get_db

bp = Blueprint('settings', __name__)

# Keys the form is allowed to submit (the full settings surface).
_FORM_KEYS = tuple(settings_mod.SETTINGS_DEFAULTS.keys())


def _choices() -> dict:
    """Choice lists for the template's <select> controls."""
    import zoneinfo
    return {
        'timezones': sorted(zoneinfo.available_timezones()),
        'date_formats': settings_mod.DATE_FORMATS,
        'themes': ['', 'light', 'dark', 'nord', 'solarized', 'dracula', 'rose', 'contrast'],
        'regions': sorted(__import__('phonenumbers').SUPPORTED_REGIONS),
    }


@bp.route('/settings')
def settings_page():
    return render_template('settings.html', settings=g.settings, **_choices())


@bp.route('/settings', methods=['POST'])
def save_settings():
    updates = {k: request.form[k] for k in _FORM_KEYS if k in request.form}
    errors = settings_mod.update_settings(get_db(), updates)
    if errors:
        # Re-render with the SUBMITTED values + the same choice lists as GET.
        submitted = dict(g.settings)
        submitted.update(updates)
        return render_template(
            'settings.html', settings=submitted, errors=errors, **_choices()
        ), 400
    flash('Settings saved.', 'success')
    return redirect(url_for('settings.settings_page'))
