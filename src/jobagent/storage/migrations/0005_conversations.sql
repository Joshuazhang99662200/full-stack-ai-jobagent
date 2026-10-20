BEGIN IMMEDIATE;

CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    job_id TEXT,
    conversation_json TEXT NOT NULL CHECK (json_valid(conversation_json)),
    opened_at TEXT NOT NULL
);

-- Append-only. The current stage is folded from these rows; a second writer that
-- started from an older list collides on (conversation_id, seq) instead of
-- interleaving its events.
CREATE TABLE conversation_events (
    event_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    kind TEXT NOT NULL,
    event_json TEXT NOT NULL CHECK (json_valid(event_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (conversation_id, seq)
);

CREATE TABLE conversation_asks (
    ask_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    ask_json TEXT NOT NULL CHECK (json_valid(ask_json))
);

PRAGMA user_version = 5;
COMMIT;
