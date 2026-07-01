-- Remembered CSV column-mapping profiles (CL-0022). One row per distinct
-- header layout: after a successful import, the chosen mapping is saved keyed
-- by a signature of the file's header row, so the next import of the same
-- layout pre-fills the mapping instead of re-guessing.
CREATE TABLE IF NOT EXISTS import_profiles (
    header_signature TEXT PRIMARY KEY,
    mapping          TEXT NOT NULL,   -- JSON: {source_header: target}
    default_type     TEXT NOT NULL,
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
