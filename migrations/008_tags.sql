-- CL-0037: tags / labels for contacts (many-to-many).
--
-- `tags` holds one row per distinct label; `name` is UNIQUE with a case-
-- insensitive collation so "Family" and "family" collapse to one tag. The
-- stored casing is whatever was first typed. `contact_tags` is the join;
-- both FKs cascade so deleting a contact (or a tag) tidies the join
-- automatically. The index on tag_id backs the "contacts having tag T"
-- filter subquery (the composite PK already covers the "tags of contact C"
-- direction). Two CREATE TABLE IF NOT EXISTS statements mirror the idempotent
-- 005/006/007 pattern so the runner re-applies them cleanly under its crash
-- window (SQLite has no ADD COLUMN IF NOT EXISTS).
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS contact_tags (
    contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id)     ON DELETE CASCADE,
    PRIMARY KEY (contact_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_contact_tags_tag ON contact_tags(tag_id);
