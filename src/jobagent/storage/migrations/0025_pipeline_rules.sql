BEGIN IMMEDIATE;
CREATE TABLE pipeline_rule_reviews (
    review_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    report_json TEXT NOT NULL CHECK(json_valid(report_json)),
    recorded_at TEXT NOT NULL
);
CREATE TRIGGER pipeline_rule_reviews_no_update BEFORE UPDATE ON pipeline_rule_reviews
BEGIN SELECT RAISE(ABORT, 'Append-only optimization review'); END;
CREATE TRIGGER pipeline_rule_reviews_no_delete BEFORE DELETE ON pipeline_rule_reviews
BEGIN SELECT RAISE(ABORT, 'Append-only optimization review'); END;
CREATE TRIGGER message_rule_proposals_pipeline_no_update BEFORE UPDATE ON message_rule_proposals BEGIN SELECT RAISE(ABORT, 'Append-only owner rules'); END;
CREATE TRIGGER message_rule_proposals_pipeline_no_delete BEFORE DELETE ON message_rule_proposals BEGIN SELECT RAISE(ABORT, 'Append-only owner rules'); END;
CREATE TRIGGER message_rule_confirmations_pipeline_no_update BEFORE UPDATE ON message_rule_confirmations BEGIN SELECT RAISE(ABORT, 'Append-only owner rules'); END;
CREATE TRIGGER message_rule_confirmations_pipeline_no_delete BEFORE DELETE ON message_rule_confirmations BEGIN SELECT RAISE(ABORT, 'Append-only owner rules'); END;
PRAGMA user_version = 25;
COMMIT;
