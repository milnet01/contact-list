from __future__ import annotations

import hmac
import logging
import os
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, abort, g, render_template, request, session

from config import APP_VERSION, Config, ensure_private_dir
from db import close_db, init_db
from resources import resource_path


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=resource_path('templates'),
        static_folder=resource_path('static'),
    )

    if test_config is None:
        app.config.from_object(Config)
    else:
        app.config.update(test_config)

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    log = logging.getLogger(__name__)

    # Database lifecycle
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    # Contact photos dir (CL-0026). Default it from the credentials dir when a
    # test_config didn't set it explicitly (test_config uses update(), not
    # from_object, so Config.PHOTOS_DIR isn't present), then create it 0700.
    app.config.setdefault(
        'PHOTOS_DIR',
        os.path.join(
            app.config.get('GOOGLE_CREDENTIALS_DIR', Config.GOOGLE_CREDENTIALS_DIR),
            'photos',
        ),
    )
    ensure_private_dir(app.config['PHOTOS_DIR'])

    log.info('App initialized — database: %s', app.config['DATABASE'])

    # ------------------------------------------------------------------
    # CSRF protection
    # ------------------------------------------------------------------

    def csrf_token() -> str:
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(32)
        return session['_csrf_token']

    @app.before_request
    def _log_request() -> None:
        log.debug('%s %s', request.method, request.path)

    @app.before_request
    def _load_settings() -> None:
        import settings as settings_mod
        from db import get_db
        try:
            g.settings = settings_mod.get_settings(get_db())
        except Exception:
            # Never let a settings-load failure 500 the request; fall back to
            # defaults so the page (and error pages) still render.
            g.settings = dict(settings_mod.SETTINGS_DEFAULTS)

    @app.before_request
    def _check_csrf() -> None:
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = request.form.get('_csrf_token', '')
            expected = session.get('_csrf_token', '')
            if not token or not expected or not hmac.compare_digest(token, expected):
                abort(403)

    def contact_count() -> int:
        """Total contacts for the nav badge, cached on ``g`` for the request.

        The badge renders on every page (base.html), so the count is needed
        widely — but the contacts-list route already computes the same total.
        Caching it on ``g`` lets that route pre-seed the value and skip the
        second COUNT, and dedups the query if several templates render in one
        request (CL-0031)."""
        count = getattr(g, 'contact_count', None)
        if count is None:
            from db import get_db
            try:
                count = get_db().execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
            except Exception:
                count = 0
            g.contact_count = count
        return count

    def last_synced() -> str | None:
        """Google's last-sync timestamp for the footer, memoised on ``g``.

        Runs on every response (including error pages), so a DB failure must
        degrade to None/"Never" rather than recurse into another 500 — the same
        defensive shape as ``contact_count()`` (CL-0033)."""
        # hasattr (not a None check) distinguishes "not yet computed" from
        # "computed as None" — None is a valid cached value here.
        if not hasattr(g, 'last_synced'):
            from db import get_db
            try:
                row = get_db().execute(
                    'SELECT last_synced_at FROM sync_state WHERE id = 1'
                ).fetchone()
                g.last_synced = row['last_synced_at'] if row else None
            except Exception:
                g.last_synced = None
        return g.last_synced

    @app.context_processor
    def _inject_globals() -> dict:
        import settings as settings_mod
        return {
            'csrf_token': csrf_token,
            'active_nav': request.path,
            'app_version': APP_VERSION,
            'contact_count': contact_count(),
            'last_synced': last_synced(),
            'settings': getattr(g, 'settings', None) or settings_mod.SETTINGS_DEFAULTS,
        }

    @app.template_filter('friendly_date')
    def friendly_date(value: str) -> str:
        """Convert an ISO-8601 UTC timestamp to the user's timezone and format."""
        if not value:
            return ''
        import settings as settings_mod
        s = getattr(g, 'settings', None) or settings_mod.SETTINGS_DEFAULTS
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            dt = dt.astimezone(ZoneInfo(s['timezone']))
            fmt = settings_mod.DATE_FORMATS.get(
                s['date_format'], settings_mod.DATE_FORMATS['dmy_hm']
            )
            return dt.strftime(fmt)
        except (ValueError, AttributeError, ZoneInfoNotFoundError):
            return value

    # ------------------------------------------------------------------
    # Security headers
    # ------------------------------------------------------------------

    @app.after_request
    def _security_headers(response):
        csp = (
            "default-src 'self'; "
            "style-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            "base-uri 'self'"
        )
        response.headers['Content-Security-Policy'] = csp
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('error.html', code=403, message='Forbidden.'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html', code=404, message='Page not found.'), 404

    @app.errorhandler(500)
    def server_error(e):
        log.error('500 Internal Server Error: %s', e, exc_info=True)
        return render_template(
            'error.html', code=500, message='Something went wrong.'
        ), 500

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------

    from routes.contacts import bp as contacts_bp
    # import_export and merge attach their routes to contacts_bp; importing them
    # runs the @bp.route decorators so the routes exist before registration.
    from routes import import_export, merge  # noqa: F401
    from routes.settings import bp as settings_bp
    from routes.sync import bp as sync_bp

    app.register_blueprint(contacts_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(sync_bp)

    return app


if __name__ == '__main__':
    app = create_app()
    # Bind the literal loopback address, not 'localhost' — the latter can
    # resolve to ::1 or, under an unusual /etc/hosts, a broader interface.
    # Matches the localhost-only contract in DESIGN.md §6.3 (CL-0021).
    app.run(host='127.0.0.1', port=app.config['PORT'], debug=False)
