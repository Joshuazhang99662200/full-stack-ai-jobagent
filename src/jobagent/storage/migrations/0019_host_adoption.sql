BEGIN IMMEDIATE;
CREATE TABLE host_migration_runs (
    migration_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json))
);
CREATE TABLE host_legacy_rows (
    migration_id TEXT NOT NULL REFERENCES host_migration_runs(migration_id),
    ordinal INTEGER NOT NULL,
    row_id TEXT NOT NULL,
    intake_id TEXT NOT NULL REFERENCES job_intakes(intake_id),
    platform TEXT NOT NULL,
    source_job_id TEXT,
    job_url TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    source_line TEXT NOT NULL,
    legacy_json TEXT NOT NULL CHECK(json_valid(legacy_json)),
    legacy_snapshot_json TEXT NOT NULL CHECK(json_valid(legacy_snapshot_json)),
    tracking_proof_status TEXT NOT NULL,
    tracking_id TEXT,
    sent_claim_json TEXT CHECK(sent_claim_json IS NULL OR json_valid(sent_claim_json)),
    sent_claim_digest TEXT,
    PRIMARY KEY(migration_id, row_id),
    UNIQUE(migration_id, ordinal)
);
CREATE TABLE host_page_observations (
    observation_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    source TEXT NOT NULL,
    surface TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    observation_json TEXT NOT NULL CHECK(json_valid(observation_json)),
    response_json TEXT NOT NULL CHECK(json_valid(response_json))
);
CREATE TABLE host_round_reports (
    report_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    report_json TEXT NOT NULL CHECK(json_valid(report_json))
);
PRAGMA user_version = 19;
COMMIT;
