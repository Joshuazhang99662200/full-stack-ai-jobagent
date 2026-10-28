BEGIN;
CREATE TABLE sourcing_runs (
    run_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    run_json TEXT NOT NULL CHECK (json_valid(run_json))
);
CREATE TABLE sourcing_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES sourcing_runs(run_id),
    source TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('query', 'detail')),
    occurred_at TEXT NOT NULL,
    attempt_json TEXT NOT NULL CHECK (json_valid(attempt_json))
);
CREATE INDEX sourcing_attempts_day_idx ON sourcing_attempts(source, occurred_at);
CREATE INDEX sourcing_attempts_run_idx ON sourcing_attempts(run_id);
CREATE TABLE sourcing_results (
    attempt_id TEXT PRIMARY KEY REFERENCES sourcing_attempts(attempt_id),
    source TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json))
);
CREATE INDEX sourcing_results_day_idx ON sourcing_results(source, completed_at);
CREATE TABLE sourcing_legacy_reads (
    source TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    observed_day TEXT NOT NULL,
    PRIMARY KEY (source, source_job_id, observed_day)
);
PRAGMA user_version = 14;
COMMIT;
