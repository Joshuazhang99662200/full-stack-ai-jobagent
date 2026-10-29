BEGIN IMMEDIATE;
CREATE TABLE pipeline_migration_runs (
    migration_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json))
);
CREATE TABLE pipeline_migration_rows (
    migration_id TEXT NOT NULL REFERENCES pipeline_migration_runs(migration_id),
    row_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    pipeline_id TEXT REFERENCES pipeline_jobs(pipeline_id),
    intake_id TEXT REFERENCES job_intakes(intake_id),
    source_digest TEXT NOT NULL,
    source_line TEXT NOT NULL,
    PRIMARY KEY(migration_id, row_id),
    UNIQUE(migration_id, ordinal)
);
PRAGMA user_version = 23;
COMMIT;
