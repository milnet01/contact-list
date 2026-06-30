import logging
import os
import sqlite3

from flask import current_app, g

log = logging.getLogger(__name__)


def get_db() -> sqlite3.Connection:
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
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
    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')
    migration_files = sorted(
        f for f in os.listdir(migrations_dir) if f.endswith('.sql')
    )
    for filename in migration_files:
        log.info('Running migration: %s', filename)
        with open(os.path.join(migrations_dir, filename)) as f:
            db.executescript(f.read())
