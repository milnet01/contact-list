-- CL-0026: contact photos/avatars.
-- One row per contact that has a stored photo file. The image bytes live on
-- disk under PHOTOS_DIR as <contact_id>.<ext>; only the extension is in the DB
-- (so the serve route knows the MIME type without sniffing). A separate table,
-- not a column on contacts, keeps the migration idempotent (CREATE TABLE IF NOT
-- EXISTS; SQLite has no ADD COLUMN IF NOT EXISTS) and cascades on delete like
-- custom_fields. The on-disk file is unlinked explicitly by the app.
CREATE TABLE IF NOT EXISTS contact_photos (
    contact_id  INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    ext         TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
