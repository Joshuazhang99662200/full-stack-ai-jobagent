BEGIN IMMEDIATE;
CREATE TABLE configuration_initializations (
    candidate_id TEXT PRIMARY KEY,
    rules_version TEXT NOT NULL REFERENCES dynamic_rule_versions(version),
    initialized_at TEXT NOT NULL
);
INSERT INTO configuration_initializations (candidate_id, rules_version, initialized_at)
SELECT h.candidate_id, h.version, json_extract(v.snapshot_json, '$.effective_at')
FROM dynamic_rule_heads h JOIN dynamic_rule_versions v ON v.version = h.version;
CREATE TRIGGER configuration_initializations_no_update
BEFORE UPDATE ON configuration_initializations
BEGIN SELECT RAISE(ABORT, 'configuration initialization is immutable'); END;
CREATE TRIGGER configuration_initializations_no_delete
BEFORE DELETE ON configuration_initializations
BEGIN SELECT RAISE(ABORT, 'configuration initialization is immutable'); END;
CREATE TABLE configuration_owner_consumptions (
    candidate_id TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    name TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('reusable', 'round')),
    run_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL REFERENCES dynamic_rule_proposals(proposal_id),
    event_id TEXT NOT NULL,
    consumed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (candidate_id, source_reference, actor_id, name, scope, run_id)
);
CREATE UNIQUE INDEX configuration_owner_actual_source_idx
ON configuration_owner_consumptions(candidate_id, source_reference, actor_id, name);
INSERT OR IGNORE INTO configuration_owner_consumptions
(candidate_id, source_reference, actor_id, name, scope, run_id, proposal_id, event_id, consumed_at)
SELECT p.candidate_id,
       json_extract(p.proposal_json, '$.request.owner_request.source_reference'),
       json_extract(p.proposal_json, '$.request.owner_request.actor_id'),
       json_extract(p.proposal_json, '$.request.name'),
       'reusable', '', p.proposal_id, p.proposal_id,
       json_extract(c.confirmation_json, '$.confirmed_at')
FROM dynamic_rule_proposals p JOIN dynamic_rule_confirmations c ON c.proposal_id = p.proposal_id
WHERE json_extract(p.proposal_json, '$.request.owner_request.source_reference') IS NOT NULL
  AND coalesce(json_extract(p.proposal_json, '$.request.owner_request.scope'), 'reusable') = 'reusable'
ORDER BY c.rowid;
CREATE TRIGGER configuration_owner_consumptions_no_update
BEFORE UPDATE ON configuration_owner_consumptions
BEGIN SELECT RAISE(ABORT, 'owner request consumption is immutable'); END;
CREATE TRIGGER configuration_owner_consumptions_no_delete
BEFORE DELETE ON configuration_owner_consumptions
BEGIN SELECT RAISE(ABORT, 'owner request consumption is immutable'); END;
PRAGMA user_version = 31;
COMMIT;
