-- Additional indexes for email/phone search and custom field uniqueness

CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cf_unique ON custom_fields(contact_id, field_name COLLATE NOCASE);
