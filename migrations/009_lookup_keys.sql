-- CL-0066: precomputed lookup keys for the alpha nav and duplicate detection.
--
-- Two hot paths did per-row work in Python on every render. get_letter_counts
-- grouped on first_letter(), an application-defined SQLite function, and
-- SQLite cannot index one -- so both the counts and the ?letter= filter
-- scanned contacts with an interpreter round trip per row, against DESIGN
-- 7.2's "indexes on all columns used in WHERE/ORDER BY". The duplicate
-- finders called phoneutil.normalize_e164 per row for the same reason, on
-- every contact create and update. Both keys are precomputed here and
-- indexed, so each becomes an indexed lookup or a GROUP BY over an index.
--
-- A side table rather than ALTER TABLE ADD COLUMN: SQLite has no ADD COLUMN
-- IF NOT EXISTS, and the runner re-runs a migration whose schema_version row
-- was not durable yet, so a non-idempotent statement would fail the retry.
-- CREATE TABLE IF NOT EXISTS re-runs cleanly -- the same reason 005/006/007/
-- 008 are side tables.
--
-- The FK cascades, so deleting a contact reaps its row. models.py maintains
-- both values inside every transaction that writes contacts.name or
-- contacts.phone, backfills rows it finds missing, and recomputes phone_key
-- when the phone_region setting changes (the E.164 form is region-dependent).
CREATE TABLE IF NOT EXISTS contact_lookup (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    letter      TEXT NOT NULL,
    phone_key   TEXT
);

CREATE INDEX IF NOT EXISTS idx_lookup_letter ON contact_lookup(letter);
CREATE INDEX IF NOT EXISTS idx_lookup_phone  ON contact_lookup(phone_key);

-- idx_contacts_email (002) could never be used: every email lookup wraps the
-- column in LOWER() and search uses a leading-wildcard LIKE, so the planner
-- never reached it while every write still maintained it. An index on the
-- LOWER(email) expression is the one the duplicate scan's GROUP BY and its
-- per-group lookup actually use. LOWER is a built-in deterministic function,
-- so SQLite allows it in an index expression; first_letter() is not, which is
-- why the letter above is stored rather than indexed in place.
DROP INDEX IF EXISTS idx_contacts_email;
CREATE INDEX IF NOT EXISTS idx_contacts_email_lower ON contacts(LOWER(email));

-- idx_contacts_phone (002) had one reader: find_duplicates' fallback branch,
-- `WHERE phone = ?`, for a number phonenumbers could not parse. That branch is
-- gone -- an unparseable number now keys on its raw string in phone_key and is
-- found through idx_lookup_phone like any other. No query filters, joins or
-- sorts on contacts.phone any more (search uses a leading-wildcard LIKE, which
-- no index serves), so this one is now pure write cost.
DROP INDEX IF EXISTS idx_contacts_phone;
