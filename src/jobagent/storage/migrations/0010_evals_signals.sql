BEGIN IMMEDIATE;

-- The first time a board showed our latest message as delivered or as read.
-- One row per status: a later snapshot never moves it, so the first sighting stands.
CREATE TABLE conversation_receipts (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    status TEXT NOT NULL CHECK (status IN ('delivered', 'read')),
    observed_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    PRIMARY KEY (conversation_id, status)
);

-- Which search turned up a posting. Kept apart from job_provenance, which is
-- rewritten whenever a job is saved again; these rows are only ever added.
CREATE TABLE job_search_hits (
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    search_term TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (job_id, search_term, collected_at)
);

CREATE INDEX job_search_hits_term_idx ON job_search_hits(search_term);

-- The files that steered drafting at one moment, addressed by their digest.
CREATE TABLE harness_versions (
    version_id TEXT PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    version_json TEXT NOT NULL CHECK (json_valid(version_json)),
    recorded_at TEXT NOT NULL
);

-- Every online profile a patrol read, kept whole; append-only.
CREATE TABLE profile_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    digest TEXT NOT NULL,
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json))
);

CREATE INDEX profile_snapshots_by_platform ON profile_snapshots(platform, captured_at);

-- A new row whenever a board's profile digest changes; append-only.
CREATE TABLE profile_versions (
    version_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    digest TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    version_json TEXT NOT NULL CHECK (json_valid(version_json))
);

CREATE INDEX profile_versions_by_platform ON profile_versions(platform, effective_at);

PRAGMA user_version = 10;

COMMIT;
