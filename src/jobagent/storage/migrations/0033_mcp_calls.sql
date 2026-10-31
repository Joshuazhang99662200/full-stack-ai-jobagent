BEGIN IMMEDIATE;
CREATE TABLE mcp_rounds (
    run_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    source TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    run_json TEXT NOT NULL CHECK(json_valid(run_json))
);
CREATE UNIQUE INDEX mcp_rounds_sourcing_binding_idx
ON mcp_rounds(json_extract(run_json, '$.sourcing_run_id'));
CREATE TABLE mcp_round_activations (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE REFERENCES mcp_rounds(run_id),
    previous_run_id TEXT REFERENCES mcp_rounds(run_id),
    previous_delivery_debit INTEGER NOT NULL CHECK(previous_delivery_debit >= 0),
    activated_at TEXT NOT NULL
);
CREATE TABLE mcp_round_closures (
    run_id TEXT PRIMARY KEY REFERENCES mcp_rounds(run_id),
    closed_at TEXT NOT NULL,
    successful_deliveries INTEGER NOT NULL CHECK(successful_deliveries >= 0)
);
CREATE TABLE mcp_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES mcp_rounds(run_id),
    request_digest TEXT NOT NULL,
    opened_at TEXT NOT NULL
);
CREATE TABLE mcp_calls (
    call_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES mcp_batches(batch_id),
    run_id TEXT NOT NULL REFERENCES mcp_rounds(run_id),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    admitted_at TEXT NOT NULL
);
CREATE TABLE mcp_dispatches (
    call_id TEXT PRIMARY KEY REFERENCES mcp_calls(call_id),
    dispatched_at TEXT NOT NULL,
    sourcing_attempt_id TEXT NOT NULL UNIQUE REFERENCES sourcing_attempts(attempt_id)
);
CREATE TABLE mcp_results (
    call_id TEXT PRIMARY KEY REFERENCES mcp_calls(call_id),
    result_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json))
);
CREATE TABLE mcp_reconciliations (
    call_id TEXT PRIMARY KEY REFERENCES mcp_results(call_id),
    reconciliation_json TEXT NOT NULL CHECK(json_valid(reconciliation_json)),
    receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json))
);
CREATE TABLE mcp_delivery_actions (
    action_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES mcp_rounds(run_id),
    intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
    prepared_at TEXT NOT NULL
);
CREATE TABLE mcp_delivery_observations (
    action_id TEXT PRIMARY KEY REFERENCES mcp_delivery_actions(action_id),
    external_reference TEXT UNIQUE,
    observation_json TEXT NOT NULL CHECK(json_valid(observation_json))
);
CREATE TABLE mcp_delivery_reconciliations (
    action_id TEXT PRIMARY KEY REFERENCES mcp_delivery_observations(action_id),
    external_reference TEXT UNIQUE,
    observation_json TEXT NOT NULL CHECK(json_valid(observation_json))
);
CREATE TRIGGER mcp_rounds_no_update BEFORE UPDATE ON mcp_rounds BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_rounds_no_delete BEFORE DELETE ON mcp_rounds BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_activations_no_update BEFORE UPDATE ON mcp_round_activations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_activations_no_delete BEFORE DELETE ON mcp_round_activations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_closures_no_update BEFORE UPDATE ON mcp_round_closures BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_closures_no_delete BEFORE DELETE ON mcp_round_closures BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_batches_no_update BEFORE UPDATE ON mcp_batches BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_batches_no_delete BEFORE DELETE ON mcp_batches BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_calls_no_update BEFORE UPDATE ON mcp_calls BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_calls_no_delete BEFORE DELETE ON mcp_calls BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_dispatches_no_update BEFORE UPDATE ON mcp_dispatches BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_dispatches_no_delete BEFORE DELETE ON mcp_dispatches BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_results_no_update BEFORE UPDATE ON mcp_results BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_results_no_delete BEFORE DELETE ON mcp_results BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_reconciliations_no_update BEFORE UPDATE ON mcp_reconciliations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_reconciliations_no_delete BEFORE DELETE ON mcp_reconciliations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_delivery_actions_no_update BEFORE UPDATE ON mcp_delivery_actions BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_delivery_actions_no_delete BEFORE DELETE ON mcp_delivery_actions BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_delivery_observations_no_update BEFORE UPDATE ON mcp_delivery_observations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_delivery_observations_no_delete BEFORE DELETE ON mcp_delivery_observations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_delivery_reconciliations_no_update BEFORE UPDATE ON mcp_delivery_reconciliations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
CREATE TRIGGER mcp_delivery_reconciliations_no_delete BEFORE DELETE ON mcp_delivery_reconciliations BEGIN SELECT RAISE(ABORT, 'MCP evidence is immutable'); END;
PRAGMA user_version = 33;
COMMIT;
