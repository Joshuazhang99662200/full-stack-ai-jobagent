BEGIN IMMEDIATE;

-- 0004 limited results to four values; the withdrawn result added with 0009 could
-- not be stored. SQLite cannot alter a CHECK, so the table is rebuilt as-is
-- with the wider list and every existing row copied across unchanged.
CREATE TABLE outreach_audits_next (
    audit_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    number INTEGER NOT NULL CHECK (number >= 1),
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    result TEXT NOT NULL CHECK (
        result IN ('sent', 'duplicate_found', 'failed', 'intervention', 'withdrawn')
    ),
    audit_json TEXT NOT NULL CHECK (json_valid(audit_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (batch_id, number)
);

INSERT INTO outreach_audits_next
    (audit_id, batch_id, number, job_id, platform, result, audit_json, recorded_at)
SELECT audit_id, batch_id, number, job_id, platform, result, audit_json, recorded_at
FROM outreach_audits;

DROP TABLE outreach_audits;
ALTER TABLE outreach_audits_next RENAME TO outreach_audits;
CREATE INDEX outreach_audits_platform_idx ON outreach_audits(platform, recorded_at);

PRAGMA user_version = 11;

COMMIT;
