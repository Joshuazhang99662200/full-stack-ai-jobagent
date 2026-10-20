BEGIN IMMEDIATE;

-- A batch, the question put to a person, and their answer are stored as written.
CREATE TABLE outreach_batches (
    batch_id TEXT PRIMARY KEY,
    batch_json TEXT NOT NULL CHECK (json_valid(batch_json)),
    created_at TEXT NOT NULL
);

CREATE TABLE outreach_asks (
    ask_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES outreach_batches(batch_id),
    ask_json TEXT NOT NULL CHECK (json_valid(ask_json))
);

CREATE TABLE outreach_approvals (
    approval_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE REFERENCES outreach_batches(batch_id),
    approval_json TEXT NOT NULL CHECK (json_valid(approval_json))
);

-- Append-only. One row per item: every result is final, nothing is retried.
-- Caps, intervals and same-day halts are all derived from these rows.
CREATE TABLE outreach_audits (
    audit_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    number INTEGER NOT NULL CHECK (number >= 1),
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    result TEXT NOT NULL CHECK (
        result IN ('sent', 'duplicate_found', 'failed', 'intervention')
    ),
    audit_json TEXT NOT NULL CHECK (json_valid(audit_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (batch_id, number)
);

CREATE INDEX outreach_audits_platform_idx ON outreach_audits(platform, recorded_at);

-- One sending session per platform at a time.
CREATE TABLE outreach_leases (
    platform TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

PRAGMA user_version = 4;
COMMIT;
