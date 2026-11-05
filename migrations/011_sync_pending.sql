-- CL-0121: a Google-linked contact whose local edit a sync could not push.
-- `since` is the sync baseline the edit dates from, so the next sync judges
-- the conflict as the failed one would have. One row per contact replaces
-- holding the shared baseline back, which kept every contact dirty.
CREATE TABLE IF NOT EXISTS sync_pending (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    since       TEXT
);
