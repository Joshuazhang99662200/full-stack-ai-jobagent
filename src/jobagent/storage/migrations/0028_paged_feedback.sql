BEGIN IMMEDIATE;

CREATE TABLE paged_card_states (
    message_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    state_json TEXT NOT NULL CHECK (json_valid(state_json))
);
CREATE TABLE paged_card_events (
    event_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES paged_card_states(message_id),
    recorded_at TEXT NOT NULL
);
CREATE TABLE sourcing_feedback_events (
    event_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    event_json TEXT NOT NULL CHECK (json_valid(event_json)),
    occurred_at TEXT NOT NULL
);
CREATE TABLE sourcing_feedback_strategies (
    version TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    strategy_json TEXT NOT NULL CHECK (json_valid(strategy_json))
);
CREATE TRIGGER sourcing_feedback_no_update BEFORE UPDATE ON sourcing_feedback_events
BEGIN SELECT RAISE(ABORT, 'feedback is append only'); END;
CREATE TRIGGER sourcing_feedback_no_delete BEFORE DELETE ON sourcing_feedback_events
BEGIN SELECT RAISE(ABORT, 'feedback is append only'); END;

PRAGMA user_version = 28;
COMMIT;
