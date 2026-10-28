BEGIN IMMEDIATE;
CREATE TABLE message_diff_events (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES normalized_jobs(job_id),
    draft_reference TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    input_json TEXT NOT NULL CHECK(json_valid(input_json)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json))
);
CREATE TABLE message_rule_proposals (
    proposal_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    proposal_json TEXT NOT NULL CHECK(json_valid(proposal_json))
);
CREATE TABLE message_rule_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL REFERENCES message_rule_proposals(proposal_id),
    input_digest TEXT NOT NULL,
    confirmation_json TEXT NOT NULL CHECK(json_valid(confirmation_json))
);
PRAGMA user_version = 21;
COMMIT;
