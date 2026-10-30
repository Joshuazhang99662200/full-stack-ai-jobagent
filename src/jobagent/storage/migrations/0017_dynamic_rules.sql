BEGIN IMMEDIATE;
CREATE TABLE dynamic_rule_proposals (
    proposal_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    proposal_json TEXT NOT NULL CHECK(json_valid(proposal_json))
);
CREATE TABLE dynamic_rule_versions (
    version TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES dynamic_rule_proposals(proposal_id),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    notice_json TEXT NOT NULL CHECK(json_valid(notice_json))
);
CREATE TABLE dynamic_rule_heads (
    candidate_id TEXT PRIMARY KEY,
    version TEXT NOT NULL REFERENCES dynamic_rule_versions(version)
);
CREATE TABLE dynamic_rule_confirmations (
    proposal_id TEXT PRIMARY KEY REFERENCES dynamic_rule_proposals(proposal_id),
    version TEXT NOT NULL REFERENCES dynamic_rule_versions(version),
    confirmation_json TEXT NOT NULL CHECK(json_valid(confirmation_json))
);
CREATE TABLE dynamic_rule_announcements (
    version TEXT PRIMARY KEY REFERENCES dynamic_rule_versions(version),
    candidate_id TEXT NOT NULL,
    delivery_reference TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL
);
CREATE TRIGGER dynamic_versions_no_update BEFORE UPDATE ON dynamic_rule_versions
BEGIN SELECT RAISE(ABORT, 'rule history is append only'); END;
CREATE TRIGGER dynamic_versions_no_delete BEFORE DELETE ON dynamic_rule_versions
BEGIN SELECT RAISE(ABORT, 'rule history is append only'); END;
CREATE TRIGGER dynamic_proposals_no_update BEFORE UPDATE ON dynamic_rule_proposals
BEGIN SELECT RAISE(ABORT, 'rule proposals are immutable'); END;
CREATE TRIGGER dynamic_proposals_no_delete BEFORE DELETE ON dynamic_rule_proposals
BEGIN SELECT RAISE(ABORT, 'rule proposals are immutable'); END;
CREATE TRIGGER dynamic_confirmations_no_update BEFORE UPDATE ON dynamic_rule_confirmations
BEGIN SELECT RAISE(ABORT, 'rule confirmations are immutable'); END;
CREATE TRIGGER dynamic_confirmations_no_delete BEFORE DELETE ON dynamic_rule_confirmations
BEGIN SELECT RAISE(ABORT, 'rule confirmations are immutable'); END;
PRAGMA user_version = 17;
COMMIT;
