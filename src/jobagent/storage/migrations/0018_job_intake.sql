BEGIN IMMEDIATE;
CREATE TABLE job_intakes (
    intake_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    target_key TEXT NOT NULL UNIQUE,
    state_json TEXT NOT NULL CHECK(json_valid(state_json))
);
CREATE INDEX job_intakes_scope ON job_intakes(candidate_id, domain);
CREATE TABLE intake_events (
    event_id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES job_intakes(intake_id),
    version INTEGER NOT NULL,
    input_digest TEXT NOT NULL,
    event_json TEXT NOT NULL CHECK(json_valid(event_json)),
    UNIQUE(intake_id, version)
);
CREATE TABLE intake_requests (
    request_id TEXT PRIMARY KEY,
    input_digest TEXT NOT NULL,
    intake_id TEXT NOT NULL REFERENCES job_intakes(intake_id)
);
CREATE TABLE intake_signals (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    intake_id TEXT NOT NULL REFERENCES job_intakes(intake_id),
    signal_json TEXT NOT NULL CHECK(json_valid(signal_json))
);
CREATE TABLE intake_active_strategies (
    candidate_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    source TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    strategy_json TEXT NOT NULL CHECK(json_valid(strategy_json)),
    PRIMARY KEY(candidate_id, domain, source)
);
CREATE TABLE intake_strategy_claims (
    run_id TEXT PRIMARY KEY REFERENCES sourcing_runs(run_id),
    candidate_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    claim_json TEXT NOT NULL CHECK(json_valid(claim_json))
);
CREATE TABLE intake_search_executions (
    attempt_id TEXT PRIMARY KEY REFERENCES sourcing_results(attempt_id),
    run_id TEXT NOT NULL REFERENCES intake_strategy_claims(run_id),
    execution_json TEXT NOT NULL CHECK(json_valid(execution_json))
);
CREATE TABLE intake_selections (
    candidate_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    list_version TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    selection_json TEXT NOT NULL CHECK(json_valid(selection_json)),
    PRIMARY KEY(candidate_id, platform, list_version)
);
PRAGMA user_version = 18;
COMMIT;
