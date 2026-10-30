BEGIN IMMEDIATE;

CREATE TABLE job_observations (
    observation_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES normalized_jobs(job_id),
    content_digest TEXT,
    record_json TEXT CHECK(record_json IS NULL OR json_valid(record_json)),
    normalized_json TEXT NOT NULL CHECK(json_valid(normalized_json)),
    kind TEXT NOT NULL CHECK(kind IN ('captured', 'normalized_only', 'legacy_normalized')),
    collected_at TEXT NOT NULL
);
INSERT INTO job_observations
SELECT 'LEGACY_' || job_id, job_id, NULL, NULL, job_json, 'legacy_normalized', created_at
FROM normalized_jobs;
CREATE INDEX job_observations_job_idx ON job_observations(job_id, collected_at);
CREATE UNIQUE INDEX job_observations_read_idx
ON job_observations(json_extract(record_json, '$.read_attempt_id'))
WHERE json_extract(record_json, '$.read_attempt_id') IS NOT NULL;
CREATE TRIGGER job_observations_no_update BEFORE UPDATE ON job_observations
BEGIN SELECT RAISE(ABORT, 'observations are append only'); END;
CREATE TRIGGER job_observations_no_delete BEFORE DELETE ON job_observations
BEGIN SELECT RAISE(ABORT, 'observations are append only'); END;

CREATE TABLE feedback_strategy_heads (
    scope_key TEXT PRIMARY KEY,
    version TEXT NOT NULL REFERENCES sourcing_feedback_strategies(version)
);
CREATE TABLE feedback_consumptions (
    scope_key TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES sourcing_feedback_events(event_id),
    version TEXT NOT NULL REFERENCES sourcing_feedback_strategies(version),
    PRIMARY KEY(scope_key, event_id)
);
CREATE TABLE sourcing_read_attempts (
    attempt_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    platform_day TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    reserved_at TEXT NOT NULL,
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json))
);
CREATE INDEX sourcing_reads_day_idx ON sourcing_read_attempts(source, platform_day);
CREATE TABLE sourcing_read_halts (
    source TEXT NOT NULL,
    platform_day TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(source, platform_day)
);

PRAGMA user_version = 16;
COMMIT;
