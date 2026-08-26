BEGIN IMMEDIATE;

-- Audits are deliberately standalone: a delivery attempt must be recordable even
-- when the job row was never persisted, and an audit must outlive its job.
CREATE TABLE application_audits (
    audit_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    result TEXT NOT NULL CHECK (
        result IN ('sent', 'failed', 'user_intervention_required')
    ),
    audit_json TEXT NOT NULL CHECK (json_valid(audit_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (application_id, attempt)
);

CREATE INDEX application_audits_application_idx
    ON application_audits(application_id, attempt);

PRAGMA user_version = 3;
COMMIT;
