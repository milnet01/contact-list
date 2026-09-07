import logging
import os
import secrets
import sys
import tempfile

# Single source of truth for the app version. Shown in the footer and bumped by
# the /bump recipe (.claude/bump.json). The git release tag (v<APP_VERSION>) and
# the top CHANGELOG heading must match this — packaging/check-version-drift.sh
# enforces the lockstep.
APP_VERSION = '1.1.0'

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
    except (OSError, UnicodeDecodeError):
        # Catching FileNotFoundError alone let a PermissionError, an
        # IsADirectoryError or a decode error escape -- from a call made in the
        # Config class body, i.e. at IMPORT, before launcher.py installs file
        # logging, on a build whose stdout is None. The app then failed to start
        # with no message on any surface (CL-0069). An unreadable key file is
        # the same situation as an absent one: mint a new key below.
        _log.warning('Could not read the stored secret key; generating a new one')

    key = secrets.token_hex(32)
    try:
        ensure_private_dir(_CONFIG_DIR)
        # O_EXCL plus a temp-and-rename, because the previous read-then-truncate
        # had two failure modes on a fresh install (CL-0069). Two copies starting
        # at once each minted a different key and each O_TRUNC'd the file, so the
        # loser signed cookies with a key that was in no file and 403'd every
        # POST -- the exact failure persisting the key was meant to fix. And a
        # crash between truncate and write left a zero-byte file, which the read
        # above treats as absent, silently rotating the key on the next start.
        #
        # Whoever wins the O_EXCL race owns the file; everyone else re-reads it
        # and uses the winner's key, so all workers agree.
        fd, tmp = tempfile.mkstemp(dir=_CONFIG_DIR, prefix='secret_key.', suffix='.tmp')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(key)
            try:
                os.link(tmp, key_path)
            except FileExistsError:
                # Another process got there first. Its key is the real one.
                with open(key_path, encoding='utf-8') as f:
                    winner = f.read().strip()
                if winner:
                    return winner
                # Zero-byte file from an older crash: replace it outright.
                os.replace(tmp, key_path)
                return key
        finally:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
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


DEFAULT_PORT = 5002
# PORT is how an automated process manager names a port, and a manager never has
# a good reason to ask for a privileged one. CONTACT_LIST_PORT (a human choosing
# a port for their own program) keeps its original range: none (CL-0056).
PORT_MIN = 1024
PORT_MAX = 65535


class PortError(ValueError):
    """An environment-supplied port the server cannot honour.

    Raised by :func:`resolve_port` only — never at import of this module, since
    app.py imports config at module level and a raise there is an import-time
    traceback in the test suite as well as at runtime.
    """


def _contact_list_port() -> int:
    """``CONTACT_LIST_PORT`` → 5002, the human-facing knob.

    Any integer is accepted (no range check — unchanged behaviour). A
    non-integer warns and falls back instead of raising, because this runs at
    import of config where a traceback helps nobody; previously it was an
    unhandled ValueError.
    """
    raw = os.environ.get('CONTACT_LIST_PORT')
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        _log.warning(
            'CONTACT_LIST_PORT=%r is not a number; falling back to %d', raw, DEFAULT_PORT
        )
        return DEFAULT_PORT


def resolve_port(default: int | None = None) -> tuple[int, bool]:
    """Resolve the port to bind. Precedence: ``PORT`` → ``default`` (which the
    callers pass as ``Config.PORT``, i.e. ``CONTACT_LIST_PORT`` → 5002).

    Returns ``(port, explicit)``; ``explicit`` is True only when ``PORT`` supplied
    the value, which is what lets the launcher treat "the port I was told to use
    is busy" as a failure rather than a hand-off (CL-0056).

    Exactly three cases, mutually exclusive:
      * ``PORT`` valid (integer in [1024, 65535]) → that port, explicit.
      * ``PORT`` absent (unset or empty) → ``default``, not explicit.
      * ``PORT`` present but malformed or out of range → :class:`PortError`.
        Never a silent fall back: a manager that asked for port 80 and was given
        5002 without being told has been lied to.
    """
    raw = os.environ.get('PORT')
    if raw is None or raw == '':
        return (DEFAULT_PORT if default is None else default), False
    try:
        port = int(raw)
    except ValueError:
        raise PortError(
            f'PORT={raw!r} is not a number '
            f'(expected an integer {PORT_MIN}-{PORT_MAX})'
        ) from None
    if not PORT_MIN <= port <= PORT_MAX:
        raise PortError(
            f'PORT={raw!r} is out of range (expected {PORT_MIN}-{PORT_MAX})'
        )
    return port, True


def _default_db_path() -> str:
    """Default DB location. Frozen: the persistent config dir (so contacts survive
    quit). From source: next to the code, unchanged. Reads sys.frozen on each call
    so tests can monkeypatch it; Config.DATABASE binds the result at import.
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(_CONFIG_DIR, 'contacts.db')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db')


class Config:
    SECRET_KEY = _load_or_create_secret_key()
    DATABASE = os.environ.get('CONTACT_LIST_DB', _default_db_path())
    GOOGLE_CREDENTIALS_DIR = _CONFIG_DIR
    GOOGLE_CREDENTIALS_FILE = os.path.join(GOOGLE_CREDENTIALS_DIR, 'credentials.json')
    GOOGLE_TOKEN_FILE = os.path.join(GOOGLE_CREDENTIALS_DIR, 'token.json')
    # Contact photos are stored as files here (not blobs in the DB), 0700 like
    # the token dir. Only the file extension is recorded in the DB (CL-0026).
    PHOTOS_DIR = os.path.join(_CONFIG_DIR, 'photos')
    # The CONTACT_LIST_PORT → 5002 fallback. PORT overrides it at the bind site
    # via resolve_port(); it does not replace it (CL-0056).
    PORT = _contact_list_port()
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
