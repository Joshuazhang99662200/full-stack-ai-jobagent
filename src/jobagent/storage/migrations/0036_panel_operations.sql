BEGIN IMMEDIATE;

-- Each panel decision as the panel will read it back, keyed by its operation key.
CREATE TABLE panel_operations (
    event_id TEXT PRIMARY KEY REFERENCES paged_card_events(event_id),
    candidate_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    event_json TEXT NOT NULL CHECK (json_valid(event_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (candidate_id, operation_key)
);
CREATE TRIGGER panel_operations_no_update BEFORE UPDATE ON panel_operations
BEGIN SELECT RAISE(ABORT, 'panel operations are append only'); END;
CREATE TRIGGER panel_operations_no_delete BEFORE DELETE ON panel_operations
BEGIN SELECT RAISE(ABORT, 'panel operations are append only'); END;

PRAGMA user_version = 36;
COMMIT;
