import logging
import os
import secrets

_CONFIG_DIR = os.path.expanduser('~/.config/contact-list')
_log = logging.getLogger(__name__)


def ensure_private_dir(path: str) -> None:
    """Create ``path`` (and parents) if missing and lock it to 0700.

    ``makedirs``' mode is masked by the umask and never touches an already
    existing directory, so we ``chmod`` explicitly. This dir holds the Google
    OAuth token; 0700 keeps it out of reach of other local users (CL-0011).
    """
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        # Best-effort — e.g. the dir is owned by another user or on a
        # filesystem that ignores POSIX modes. The token file itself is still
        # created 0600, so this is defence-in-depth, not the only guard.
        _log.warning('Could not tighten permissions on %s to 0700', path)


def _load_or_create_secret_key() -> str:
    """Return a stable Flask secret key.

    An explicit ``SECRET_KEY`` env var always wins. Otherwise the key is
    persisted under the config dir so signed sessions and CSRF tokens survive
    app restarts and stay valid across multiple worker processes. A fresh
    ``os.urandom()`` per process (the previous behaviour) invalidated every
    open session on restart and would 403 every POST when run under more than
    one worker.
    """
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key

    key_path = os.path.join(_CONFIG_DIR, 'secret_key')
    try:
        with open(key_path, encoding='utf-8') as f:
            stored = f.read().strip()
        if stored:
            return stored
    except FileNotFoundError:
        pass

    key = secrets.token_hex(32)
    try:
        ensure_private_dir(_CONFIG_DIR)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key)
    except OSError:
        # Can't persist (e.g. read-only home dir) — fall back to an ephemeral
        # key so the app still starts; sessions just won't survive a restart.
        # Surface it rather than swallow: under multiple workers each would get
        # a different key and CSRF/session cookies would break. Set the
        # SECRET_KEY env var to a fixed value for any multi-worker deployment.
        _log.warning(
            'Could not persist a secret key under %s; using an ephemeral key. '
            'Sessions will not survive a restart. Set the SECRET_KEY env var '
            'for a stable key (required for multi-worker deployments).',
            _CONFIG_DIR,
        )
    return key


class Config:
    SECRET_KEY = _load_or_create_secret_key()
    DATABASE = os.environ.get(
        'CONTACT_LIST_DB',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db'),
    )
    GOOGLE_CREDENTIALS_DIR = _CONFIG_DIR
    GOOGLE_CREDENTIALS_FILE = os.path.join(GOOGLE_CREDENTIALS_DIR, 'credentials.json')
    GOOGLE_TOKEN_FILE = os.path.join(GOOGLE_CREDENTIALS_DIR, 'token.json')
    PORT = int(os.environ.get('CONTACT_LIST_PORT', 5002))
    CONTACTS_PER_PAGE = 50
    MAX_CONTACTS_PER_PAGE = 200
    # Hard ceiling on any request body (Flask returns 413 past it). Bounds both
    # an uploaded import file and the carried-CSV re-post on the mapping screen
    # (CL-0022). Import files are tiny for a single-user list; the handler
    # additionally rejects a decoded body over 1 MiB with a friendly message.
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    MAX_IMPORT_BYTES = 1 * 1024 * 1024
    # Browser-enforced defence-in-depth on top of the signed CSRF token: the
    # session cookie is not sent on cross-site form POSTs. 'Lax' (not 'Strict')
    # so following a normal link into the app still carries the session
    # (CL-0028). No downside on this same-origin localhost app.
    SESSION_COOKIE_SAMESITE = 'Lax'
