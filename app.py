from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timezone

from flask import Flask, abort, render_template, request, session

from config import Config
from db import close_db, init_db


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)

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
    def _check_csrf() -> None:
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = request.form.get('_csrf_token', '')
            expected = session.get('_csrf_token', '')
            if not token or not expected or not hmac.compare_digest(token, expected):
                abort(403)

    @app.context_processor
    def _inject_globals() -> dict:
        from db import get_db
        try:
            db = get_db()
            total = db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
        except Exception:
            total = 0
        return {
            'csrf_token': csrf_token,
            'active_nav': request.path,
            'contact_count': total,
        }

    @app.template_filter('friendly_date')
    def friendly_date(value: str) -> str:
        """Convert ISO 8601 timestamp to human-readable format."""
        if not value:
            return ''
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.strftime('%d %b %Y, %H:%M')
        except (ValueError, AttributeError):
            return value

    # ------------------------------------------------------------------
    # Security headers
    # ------------------------------------------------------------------

    @app.after_request
    def _security_headers(response):
        csp = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
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
    from routes.sync import bp as sync_bp

    app.register_blueprint(contacts_bp)
    app.register_blueprint(sync_bp)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='localhost', port=app.config['PORT'], debug=False)
