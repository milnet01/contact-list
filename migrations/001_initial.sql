CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT    NOT NULL CHECK(type IN ('individual', 'company')),
    name        TEXT    NOT NULL,
    email       TEXT,
    phone       TEXT,
    notes       TEXT,
    google_id   TEXT    UNIQUE,
    etag        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_type ON contacts(type);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_contacts_google_id ON contacts(google_id);

CREATE TABLE IF NOT EXISTS custom_fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    field_name  TEXT    NOT NULL,
    field_value TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_cf_contact ON custom_fields(contact_id);
CREATE INDEX IF NOT EXISTS idx_cf_name    ON custom_fields(field_name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS sync_state (
    id              INTEGER PRIMARY KEY CHECK(id = 1),
    sync_token      TEXT,
    last_synced_at  TEXT
);
