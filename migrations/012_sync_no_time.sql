-- CL-0126: how many syncs found no Google updateTime for a pending contact.
-- At google_sync.NO_TIME_GIVE_UP misses Google's copy wins, so the contact is
-- not frozen in both directions (two-way sync spec section 7).
--
-- A side table rather than a sync_pending column, for 009's reason: SQLite has
-- no ADD COLUMN IF NOT EXISTS, and a migration must re-run cleanly. It cascades
-- from sync_pending, so clearing a contact's pending mark clears its count.
CREATE TABLE IF NOT EXISTS sync_no_time (
    contact_id  INTEGER PRIMARY KEY
                REFERENCES sync_pending(contact_id) ON DELETE CASCADE,
    misses      INTEGER NOT NULL
);
