BEGIN IMMEDIATE;
CREATE TABLE host_backfill_links (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    migration_id TEXT NOT NULL,
    row_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    link_json TEXT NOT NULL CHECK(json_valid(link_json)),
    FOREIGN KEY(migration_id, row_id) REFERENCES host_legacy_rows(migration_id, row_id)
);
PRAGMA user_version = 20;
COMMIT;
