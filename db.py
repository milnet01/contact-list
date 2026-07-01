import logging
import os
import sqlite3
import unicodedata

from flask import current_app, g

log = logging.getLogger(__name__)


def _first_letter(name: str | None) -> str:
    """Folded, uppercase first letter for the alpha nav.

    Strips accents so 'Élodie' buckets under 'E'; anything whose folded initial
    isn't an ASCII A–Z (digits, symbols, non-Latin scripts) buckets under '#'.
    Registered as a SQLite function so get_letter_counts (the counts) and the
    letter filter (the query) fold identically (CL-0014).
    """
    if not name:
        return '#'
    ch = name.strip()[:1]
    if not ch:
        return '#'
    base = unicodedata.normalize('NFD', ch)[0].upper()
    return base if base.isascii() and base.isalpha() else '#'


def get_db() -> sqlite3.Connection:
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.create_function('first_letter', 1, _first_letter, deterministic=True)
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA synchronous=NORMAL')
        g.db.execute('PRAGMA busy_timeout=5000')
        g.db.execute('PRAGMA cache_size=-8000')
        g.db.execute('PRAGMA temp_store=MEMORY')
    return g.db


def close_db(e: BaseException | None = None) -> None:
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()

    # Track which migration files have been applied so each runs exactly once.
    # Without this, every *.sql re-ran on every startup and only worked because
    # each statement was IF NOT EXISTS; a future non-idempotent migration could
    # not run safely. Existing databases (no schema_version row yet) simply
    # re-run the current, idempotent migrations once and record them (CL-0008).
    db.execute(
        'CREATE TABLE IF NOT EXISTS schema_version ('
        '    filename    TEXT PRIMARY KEY,'
        "    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
        ')'
    )
    applied = {
        row['filename'] for row in db.execute('SELECT filename FROM schema_version')
    }

    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')
    migration_files = sorted(
        f for f in os.listdir(migrations_dir) if f.endswith('.sql')
    )
    for filename in migration_files:
        if filename in applied:
            continue
        log.info('Running migration: %s', filename)
        with open(os.path.join(migrations_dir, filename)) as f:
            # executescript() issues its own COMMIT, so the migration is durable
            # before the schema_version row below. A crash in that window re-runs
            # the file next boot — so every migration must stay idempotent
            # (IF NOT EXISTS / guarded DELETEs), even with version tracking.
            db.executescript(f.read())
        db.execute('INSERT INTO schema_version (filename) VALUES (?)', [filename])
    db.commit()
