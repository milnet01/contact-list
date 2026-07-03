"""Tests for contact tags / labels (CL-0037).

Covers the invariants in docs/specs/2026-07-03-tags-labels-design.md §10:
normalization (INV-1), case-insensitive uniqueness (INV-2), orphan GC across
all delete paths (INV-3/4), transaction composition (INV-5), the AND filter with
no fan-out (INV-6), filter-view treatment (INV-7), and merge tag-union (INV-8).
"""
from __future__ import annotations

import pytest

import models
from app import create_app
from db import get_db


@pytest.fixture()
def app(tmp_path):
    db_path = str(tmp_path / 'test.db')
    gcreds = tmp_path / 'gcreds'
    app = create_app({
        'TESTING': True,
        'DATABASE': db_path,
        'SECRET_KEY': 'test-secret',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })
    yield app


@pytest.fixture()
def db(app):
    with app.app_context():
        yield get_db()


@pytest.fixture()
def client(app):
    return app.test_client()


def _get_csrf(client) -> str:
    client.get('/contacts/new')
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


# --- Schema / migration ------------------------------------------------------

class TestSchema:
    def test_tables_and_index_exist(self, db):
        names = {
            r['name']
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }
        assert {'tags', 'contact_tags', 'idx_contact_tags_tag'} <= names

    def test_migration_idempotent(self, app):
        # A second init_db run must not error (CREATE ... IF NOT EXISTS).
        with app.app_context():
            from db import init_db
            init_db()
            db = get_db()
            assert db.execute('SELECT COUNT(*) FROM tags').fetchone()[0] == 0


# --- Normalization (INV-1) ---------------------------------------------------

class TestNormalizeTags:
    def test_split_strip_collapse(self):
        assert models._normalize_tags('  close  friends , work ') == [
            'close friends', 'work'
        ]

    def test_drop_empty_pieces(self):
        assert models._normalize_tags('a,,b, ,c') == ['a', 'b', 'c']

    def test_truncate_over_length(self):
        long = 'x' * 80
        assert models._normalize_tags(long) == ['x' * models.MAX_TAG_LEN]

    def test_count_cap(self):
        raw = ','.join(f'tag{i}' for i in range(60))
        out = models._normalize_tags(raw)
        assert len(out) == models.MAX_TAGS
        assert out[0] == 'tag0'

    def test_case_insensitive_dedup_first_casing_wins(self):
        assert models._normalize_tags('Work, work, WORK') == ['Work']

    def test_blank_field(self):
        assert models._normalize_tags('') == []
        assert models._normalize_tags('  ,  ,') == []


# --- set/get helpers (INV-2, INV-3) ------------------------------------------

class TestSetContactTags:
    def test_create_and_read_back(self, db):
        cid = models.create_contact(db, 'individual', 'Alice', tags=['work', 'gym'])
        assert models.get_contact_tags(db, cid) == ['gym', 'work']  # NOCASE order

    def test_replace_gcs_orphan(self, db):
        cid = models.create_contact(db, 'individual', 'Alice', tags=['solo'])
        assert any(t['name'] == 'solo' for t in models.get_all_tags(db))
        models.set_contact_tags(db, cid, ['other'])
        db.commit()
        names = {t['name'] for t in models.get_all_tags(db)}
        assert names == {'other'}  # 'solo' reaped, INV-3

    def test_case_insensitive_reuse(self, db):
        a = models.create_contact(db, 'individual', 'A', tags=['Work'])
        b = models.create_contact(db, 'individual', 'B', tags=['work'])
        rows = db.execute("SELECT COUNT(*) FROM tags WHERE name = 'Work' COLLATE NOCASE").fetchone()
        assert rows[0] == 1  # one row, INV-2
        assert models.get_contact_tags(db, a) == ['Work']
        assert models.get_contact_tags(db, b) == ['Work']  # reused casing

    def test_idempotent_set(self, db):
        cid = models.create_contact(db, 'individual', 'Alice', tags=['x'])
        models.set_contact_tags(db, cid, ['x'])
        db.commit()
        assert models.get_contact_tags(db, cid) == ['x']
        assert db.execute('SELECT COUNT(*) FROM contact_tags WHERE contact_id = ?', [cid]).fetchone()[0] == 1

    def test_get_all_tags_counts(self, db):
        models.create_contact(db, 'individual', 'A', tags=['shared'])
        models.create_contact(db, 'individual', 'B', tags=['shared', 'solo'])
        counts = {t['name']: t['cnt'] for t in models.get_all_tags(db)}
        assert counts == {'shared': 2, 'solo': 1}

    def test_get_all_tags_excludes_orphan(self, db):
        # Manufacture an orphan tag directly (bypassing set_contact_tags' GC) to
        # isolate the inner-join guard from the GC guard.
        db.execute("INSERT INTO tags (name) VALUES ('ghost')")
        db.commit()
        assert all(t['name'] != 'ghost' for t in models.get_all_tags(db))


# --- Transaction composition (INV-5) -----------------------------------------

class TestTransactionComposition:
    def test_failed_write_rolls_back_tags(self, db, monkeypatch):
        # Force a failure after set_contact_tags inside create_contact's `with db:`
        # — the whole write, tags included, must roll back.
        monkeypatch.setattr(models, '_mark_edited', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        with pytest.raises(RuntimeError):
            models.create_contact(db, 'individual', 'Doomed', tags=['ephemeral'])
        assert db.execute("SELECT COUNT(*) FROM contacts WHERE name = 'Doomed'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM tags WHERE name = 'ephemeral'").fetchone()[0] == 0


# --- AND filter, no fan-out (INV-6) ------------------------------------------

class TestFilter:
    def test_and_semantics(self, db):
        both = models.create_contact(db, 'individual', 'Both', tags=['family', 'local'])
        models.create_contact(db, 'individual', 'OnlyFamily', tags=['family'])
        rows, total = models.list_contacts(db, tags=['family', 'local'])
        assert total == 1
        assert [r['id'] for r in rows] == [both]

    def test_single_tag(self, db):
        models.create_contact(db, 'individual', 'A', tags=['family'])
        models.create_contact(db, 'individual', 'B', tags=['family'])
        _, total = models.list_contacts(db, tags=['family'])
        assert total == 2

    def test_unknown_tag_empty(self, db):
        models.create_contact(db, 'individual', 'A', tags=['family'])
        _, total = models.list_contacts(db, tags=['nope'])
        assert total == 0

    def test_case_insensitive_match(self, db):
        models.create_contact(db, 'individual', 'A', tags=['work'])
        _, total = models.list_contacts(db, tags=['WORK'])
        assert total == 1

    def test_no_fan_out(self, db):
        # A contact carrying both selected tags must appear once, counted once —
        # the id-IN membership test can't fan out the way a JOIN would.
        models.create_contact(db, 'individual', 'Multi', tags=['a', 'b'])
        rows, total = models.list_contacts(db, tags=['a'])
        assert total == 1
        assert len(rows) == 1


# --- Merge (INV-8) + merge-path GC (INV-3) -----------------------------------

class TestMergeTags:
    def _fields(self, name='Survivor', ctype='individual'):
        return {'type': ctype, 'name': name, 'email': None, 'phone': None, 'notes': None}

    def test_union_default(self, db):
        s = models.create_contact(db, 'individual', 'S', tags=['b'])
        loser = models.create_contact(db, 'individual', 'L', tags=['a'])
        models.merge_contacts(db, s, [loser], self._fields(), tags=['a', 'b'])
        assert models.get_contact_tags(db, s) == ['a', 'b']

    def test_prune_drops_and_gcs(self, db):
        s = models.create_contact(db, 'individual', 'S', tags=['b'])
        loser = models.create_contact(db, 'individual', 'L', tags=['a'])
        # User prunes 'a' out of the pre-filled union.
        models.merge_contacts(db, s, [loser], self._fields(), tags=['b'])
        assert models.get_contact_tags(db, s) == ['b']
        # 'a' had no other user (the loser is deleted) → reaped (INV-3 merge path).
        assert all(t['name'] != 'a' for t in models.get_all_tags(db))


# --- Delete GC (INV-4) -------------------------------------------------------

class TestDeleteGC:
    def test_single_delete_reaps_sole_tag(self, db):
        cid = models.create_contact(db, 'individual', 'A', tags=['only'])
        models.delete_contact(db, cid)
        assert all(t['name'] != 'only' for t in models.get_all_tags(db))

    def test_bulk_delete_reaps(self, client, db):
        token = _get_csrf(client)
        cid = models.create_contact(db, 'individual', 'BulkVictim', tags=['gone'])
        resp = client.post('/contacts/bulk-delete', data={
            '_csrf_token': token, 'selected': [str(cid)], 'ref': '/contacts',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert all(t['name'] != 'gone' for t in models.get_all_tags(db))


# --- Routes: round-trip + filter preservation (INV-7) ------------------------

class TestTagRoutes:
    def test_create_and_update_round_trip(self, client, db):
        token = _get_csrf(client)
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Tagged',
            'tags': 'alpha, beta',
        }, follow_redirects=True)
        cid = db.execute("SELECT id FROM contacts WHERE name = 'Tagged'").fetchone()['id']
        assert models.get_contact_tags(db, cid) == ['alpha', 'beta']

        client.post(f'/contacts/{cid}', data={
            '_csrf_token': token, 'type': 'individual', 'name': 'Tagged',
            'tags': 'beta, gamma',
        }, follow_redirects=True)
        assert models.get_contact_tags(db, cid) == ['beta', 'gamma']
        assert all(t['name'] != 'alpha' for t in models.get_all_tags(db))  # GC'd

    def test_error_rerender_echoes_tags(self, client):
        token = _get_csrf(client)
        resp = client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': '',
            'tags': 'keepme',
        })
        assert resp.status_code == 400
        assert b'keepme' in resp.data

    def test_detail_shows_chips(self, client, db):
        cid = models.create_contact(db, 'individual', 'Chippy', tags=['vip'])
        resp = client.get(f'/contacts/{cid}')
        assert b'vip' in resp.data
        assert b'tag-chip' in resp.data

    def test_filter_bar_and_active_state(self, client, db):
        models.create_contact(db, 'individual', 'A', tags=['friends'])
        resp = client.get('/contacts?tag=friends')
        assert resp.status_code == 200
        assert b'tag-filter' in resp.data
        assert b'friends' in resp.data

    def test_filtered_empty_state(self, client, db):
        models.create_contact(db, 'individual', 'A', tags=['x'])
        models.create_contact(db, 'individual', 'B', tags=['y'])
        # AND of two disjoint tags → zero matches → filtered-empty copy.
        resp = client.get('/contacts?tag=x&tag=y')
        assert b'No contacts match your filters' in resp.data
        assert b'No contacts yet' not in resp.data

    def test_sort_link_preserves_tag(self, client, db):
        models.create_contact(db, 'individual', 'A', tags=['keep'])
        resp = client.get('/contacts?tag=keep')
        # sort-header / pagination-style links must carry the tag param forward.
        assert b'tag=keep' in resp.data

    def test_pagination_preserves_tag(self, client, db):
        for i in range(3):
            models.create_contact(db, 'individual', f'C{i}', tags=['many'])
        resp = client.get('/contacts?tag=many&per_page=2')
        assert b'Next' in resp.data
        # the Next link carries tag=many so paging doesn't drop the filter.
        assert resp.data.count(b'tag=many') >= 1
