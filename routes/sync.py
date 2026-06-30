from __future__ import annotations

import logging
import os
import subprocess
import sys

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from db import get_db
import google_sync

log = logging.getLogger(__name__)

bp = Blueprint('sync', __name__)


@bp.route('/sync')
def sync_page():
    config = current_app.config
    db = get_db()

    sync_state = db.execute('SELECT * FROM sync_state WHERE id = 1').fetchone()

    return render_template(
        'sync.html',
        has_credentials=google_sync.has_credentials(config),
        is_authenticated=google_sync.is_authenticated(config),
        sync_state=sync_state,
    )


@bp.route('/sync/authorize', methods=['POST'])
def authorize():
    config = current_app.config

    if not google_sync.has_credentials(config):
        flash('Google credentials file not found. See setup instructions.', 'error')
        return redirect(url_for('sync.sync_page'))

    # Use InstalledAppFlow via the standalone auth script
    auth_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'google_auth.py')
    try:
        result = subprocess.run(
            [sys.executable, auth_script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            log.info('Google authentication succeeded')
            flash('Successfully connected to Google.', 'success')
        else:
            log.error('Auth script failed (rc=%d): %s', result.returncode, result.stderr)
            flash('Authentication failed. Check the logs for details.', 'error')
    except subprocess.TimeoutExpired:
        log.error('Auth script timed out after 120s')
        flash('Authentication timed out. Please try again.', 'error')
    except Exception:
        log.exception('Auth script error')
        flash('Authentication error. Check the logs for details.', 'error')

    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/start', methods=['POST'])
def start_sync():
    config = current_app.config
    db = get_db()

    count, error = google_sync.sync_contacts(config, db)
    if error:
        flash(f'Sync failed: {error}', 'error')
    else:
        flash(f'Synced {count} contact{"s" if count != 1 else ""} from Google.', 'success')

    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/disconnect', methods=['POST'])
def disconnect():
    google_sync.revoke_credentials(current_app.config)
    flash('Disconnected from Google.', 'success')
    return redirect(url_for('sync.sync_page'))
