-- CL-0039: favourite / pinned contacts.
--
-- A companion table (not a column on contacts) so the migration is idempotent
-- under the runner's crash window — SQLite has no ADD COLUMN IF NOT EXISTS, but
-- CREATE TABLE IF NOT EXISTS re-runs cleanly. Mirrors contact_photos (005) and
-- contact_edits (006). Presence of a row = the contact is a favourite; cascade
-- delete keeps it in lockstep with the contact. created_at is kept for symmetry
-- with 005/006 — no code reads it.
CREATE TABLE IF NOT EXISTS contact_favourites (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
