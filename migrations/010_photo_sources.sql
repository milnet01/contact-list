-- CL-0088: the Google photo URL a stored photo was fetched from, so a re-sync
-- can skip an unchanged photo. Its own table, not a column on contact_photos:
-- migrations must be re-runnable, and SQLite has CREATE TABLE IF NOT EXISTS but
-- no ADD COLUMN IF NOT EXISTS. A row exists only while the stored photo is the
-- one that URL names; a manual upload or removal deletes it.
CREATE TABLE IF NOT EXISTS contact_photo_sources (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    url         TEXT    NOT NULL
);
