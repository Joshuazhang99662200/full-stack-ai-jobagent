BEGIN IMMEDIATE;

-- A batch withdrawn before approval: it can no longer be approved or sent.
CREATE TABLE outreach_withdrawals (
    batch_id TEXT PRIMARY KEY REFERENCES outreach_batches(batch_id),
    reason TEXT NOT NULL,
    withdrawn_at TEXT NOT NULL
);

PRAGMA user_version = 9;

COMMIT;
