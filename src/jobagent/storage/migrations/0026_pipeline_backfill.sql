BEGIN IMMEDIATE;
CREATE TABLE pipeline_backfill_links (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    migration_id TEXT NOT NULL,
    row_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    link_json TEXT NOT NULL CHECK(json_valid(link_json)),
    FOREIGN KEY(migration_id, row_id) REFERENCES pipeline_migration_rows(migration_id, row_id)
);
CREATE TRIGGER pipeline_backfill_links_no_update BEFORE UPDATE ON pipeline_backfill_links
BEGIN SELECT RAISE(ABORT, 'Append-only backfill lineage'); END;
CREATE TRIGGER pipeline_backfill_links_no_delete BEFORE DELETE ON pipeline_backfill_links
BEGIN SELECT RAISE(ABORT, 'Append-only backfill lineage'); END;
PRAGMA user_version = 26;
COMMIT;
