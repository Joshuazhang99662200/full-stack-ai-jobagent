BEGIN IMMEDIATE;
CREATE TABLE jd_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    UNIQUE(job_id, snapshot_version)
);
CREATE TABLE jd_discoveries (
    observation_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES jd_snapshots(snapshot_id),
    job_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    discovery_json TEXT NOT NULL CHECK (json_valid(discovery_json))
);
CREATE INDEX jd_discoveries_job_idx ON jd_discoveries(job_id);
CREATE TABLE jd_feature_sets (
    feature_set_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES jd_snapshots(snapshot_id),
    lexicon_digest TEXT NOT NULL,
    feature_json TEXT NOT NULL CHECK (json_valid(feature_json)),
    recorded_at TEXT NOT NULL
);
CREATE TABLE jd_lexicon_versions (
    candidate_id TEXT NOT NULL,
    version_digest TEXT NOT NULL,
    domain TEXT NOT NULL,
    lexicon_json TEXT NOT NULL CHECK (json_valid(lexicon_json)),
    markdown_text TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, version_digest)
);
PRAGMA user_version = 15;
COMMIT;
