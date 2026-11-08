from __future__ import annotations

import logging
import os
import subprocess
import sys

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    url_for,
)
from flask.typing import ResponseReturnValue

import google_sync
from db import get_db

log = logging.getLogger(__name__)

bp = Blueprint('sync', __name__)

# Absolute path to the standalone auth script, used from source by _auth_command.
auth_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'google_auth.py')


def _auth_command(frozen: bool) -> list[str]:
    """argv for the Google-auth child. Frozen: re-invoke this binary with the flag
    (launcher.py routes it to google_auth.main()). From source: run the .py."""
    if frozen:
        return [sys.executable, '--google-auth']
    return [sys.executable, auth_script]


@bp.route('/sync')
def sync_page() -> ResponseReturnValue:
    config = current_app.config
    db = get_db()

    sync_state = db.execute('SELECT * FROM sync_state WHERE id = 1').fetchone()

    return render_template(
        'sync.html',
        has_credentials=google_sync.has_credentials(config),
        is_authenticated=google_sync.is_authenticated(config),
        needs_reconsent=google_sync.needs_reconsent(config),
        sync_state=sync_state,
    )


@bp.route('/sync/authorize', methods=['POST'])
def authorize() -> ResponseReturnValue:
    config = current_app.config

    if not google_sync.has_credentials(config):
        flash('Google credentials file not found. See setup instructions.', 'error')
        return redirect(url_for('sync.sync_page'))

    # Use InstalledAppFlow via the standalone auth script (or this binary, frozen)
    cmd = _auth_command(getattr(sys, 'frozen', False))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
            check=False,  # the return code is read below
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
def start_sync() -> ResponseReturnValue:
    config = current_app.config
    db = get_db()

    r = google_sync.sync_contacts(config, db, g.settings['phone_region'])
    summary = ', '.join(_summary_parts(r)) + '.'
    if not r.error:
        flash('Sync complete: ' + summary, 'success')
    elif _did_any_work(r):
        # CL-0116: work committed before the error stays done, so say what it was.
        flash(f'Sync failed: {r.error} Before it stopped: {summary}', 'error')
    else:
        flash(f'Sync failed: {r.error}', 'error')

    return redirect(url_for('sync.sync_page'))


def _did_any_work(r: google_sync.SyncResult) -> bool:
    return any((r.pulled, r.created, r.updated, r.conflicts_local,
                r.conflicts_google, r.push_no_time, r.skipped))


def _summary_parts(r: google_sync.SyncResult) -> list[str]:
    """The counts of one sync run, as phrases for the flash message."""
    parts = [f'{r.pulled} imported from Google']
    if r.created:
        parts.append(f'{r.created} created on Google')
    if r.updated:
        parts.append(f'{r.updated} updated')
    conflicts = r.conflicts_local + r.conflicts_google
    if conflicts:
        parts.append(
            f'{conflicts} conflict{"s" if conflicts != 1 else ""} resolved '
            f'({r.conflicts_local} kept yours, {r.conflicts_google} kept Google)')
    if r.push_no_time:
        parts.append(
            f"{r.push_no_time} edit{'s' if r.push_no_time != 1 else ''} "
            "couldn't be pushed (Google's edit time was unavailable)")
    if r.no_time_google:
        # Spec §7, CL-0126: Google's copy won after repeated misses, so name
        # the contacts whose local edit was lost.
        parts.append(
            f"Google's copy was kept for {', '.join(r.no_time_google)}, since "
            'Google gave no edit time; redo those edits')
    if r.skipped:
        parts.append(f'{r.skipped} skipped')
    return parts


@bp.route('/sync/disconnect', methods=['POST'])
def disconnect() -> ResponseReturnValue:
    google_sync.revoke_credentials(current_app.config)
    flash('Disconnected from Google.', 'success')
    return redirect(url_for('sync.sync_page'))
