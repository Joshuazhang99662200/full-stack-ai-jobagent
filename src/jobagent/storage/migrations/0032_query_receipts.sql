BEGIN IMMEDIATE;
CREATE TABLE sourcing_query_selections (
    attempt_id TEXT PRIMARY KEY REFERENCES sourcing_attempts(attempt_id),
    run_id TEXT NOT NULL REFERENCES sourcing_runs(run_id),
    request_digest TEXT NOT NULL,
    selection_json TEXT NOT NULL CHECK(json_valid(selection_json))
);
CREATE TABLE sourcing_seen_listings (
    run_id TEXT NOT NULL REFERENCES sourcing_runs(run_id),
    source_job_id TEXT NOT NULL,
    first_attempt_id TEXT NOT NULL REFERENCES sourcing_attempts(attempt_id),
    PRIMARY KEY(run_id, source_job_id)
);
CREATE TABLE sourcing_query_claims (
    attempt_id TEXT PRIMARY KEY REFERENCES sourcing_attempts(attempt_id),
    request_digest TEXT NOT NULL,
    claimed_at TEXT NOT NULL
);
CREATE TRIGGER query_selections_no_update BEFORE UPDATE ON sourcing_query_selections
BEGIN SELECT RAISE(ABORT, 'query selections are immutable'); END;
CREATE TRIGGER query_selections_no_delete BEFORE DELETE ON sourcing_query_selections
BEGIN SELECT RAISE(ABORT, 'query selections are immutable'); END;
CREATE TRIGGER query_claims_no_update BEFORE UPDATE ON sourcing_query_claims
BEGIN SELECT RAISE(ABORT, 'query claims are immutable'); END;
CREATE TRIGGER query_claims_no_delete BEFORE DELETE ON sourcing_query_claims
BEGIN SELECT RAISE(ABORT, 'query claims are immutable'); END;
PRAGMA user_version = 32;
COMMIT;
