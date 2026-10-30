BEGIN IMMEDIATE;

CREATE TABLE worker_fetch_receipts (
    task_id TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json))
);

CREATE TABLE worker_send_claims (
    task_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES outreach_batches(batch_id),
    number INTEGER NOT NULL,
    platform TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('claimed', 'authorized', 'completed')),
    claim_json TEXT NOT NULL CHECK (json_valid(claim_json)),
    readback_digest TEXT,
    receipt_json TEXT CHECK (receipt_json IS NULL OR json_valid(receipt_json)),
    UNIQUE(batch_id, number)
);
CREATE UNIQUE INDEX worker_one_open_claim_per_platform
    ON worker_send_claims(platform) WHERE status != 'completed';

CREATE TABLE worker_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    event_json TEXT NOT NULL CHECK (json_valid(event_json)),
    created_at TEXT NOT NULL
);
CREATE TABLE worker_event_acks (
    event_id TEXT PRIMARY KEY REFERENCES worker_events(event_id),
    acknowledged_at TEXT NOT NULL
);

PRAGMA user_version = 14;
COMMIT;
