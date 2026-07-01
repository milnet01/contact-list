-- Additional indexes for email/phone search and custom field uniqueness

CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);

-- Remove any pre-existing case-variant duplicate custom-field names (keeping
-- the lowest rowid per contact + case-folded name) BEFORE creating the unique
-- index, so this migration can run on an older database that already holds
-- such duplicates instead of aborting startup (CL-0008). LOWER() matches the
-- ASCII COLLATE NOCASE scope of the index below.
DELETE FROM custom_fields
WHERE rowid NOT IN (
    SELECT MIN(rowid) FROM custom_fields
    GROUP BY contact_id, LOWER(field_name)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cf_unique ON custom_fields(contact_id, field_name COLLATE NOCASE);
