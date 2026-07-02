-- CL-0033: honest "last edited by you" timestamp.
--
-- A companion table (not a column on contacts) so the migration is idempotent
-- under the runner's crash window — SQLite has no ADD COLUMN IF NOT EXISTS, but
-- CREATE TABLE IF NOT EXISTS re-runs cleanly. Mirrors the contact_photos pattern
-- (005). edited_at is written ONLY by the user-facing model writers
-- (create_contact / _write_contact / import_contact), never by the Google-sync
-- pull, so it distinguishes "you edited this" from "a sync refreshed it".
--
-- No backfill: existing contacts get no row until the user genuinely edits them,
-- so a synced-but-never-user-edited contact honestly has no last-edit time.
CREATE TABLE IF NOT EXISTS contact_edits (
    contact_id INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    edited_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
