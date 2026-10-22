BEGIN IMMEDIATE;

-- Online profile changes the agent may make only after a person approves them.
-- Every table is append-only: a proposal is never edited, a newer one replaces it.
CREATE TABLE profile_proposals (
    proposal_id TEXT PRIMARY KEY,
    proposal_json TEXT NOT NULL CHECK (json_valid(proposal_json)),
    created_at TEXT NOT NULL
);

CREATE TABLE profile_asks (
    ask_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES profile_proposals(proposal_id),
    ask_json TEXT NOT NULL CHECK (json_valid(ask_json))
);

CREATE TABLE profile_approvals (
    approval_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES profile_proposals(proposal_id),
    approval_json TEXT NOT NULL CHECK (json_valid(approval_json))
);

-- One attempt per proposal and board; the result is final.
CREATE TABLE profile_applications (
    application_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES profile_proposals(proposal_id),
    platform TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('applied', 'mismatch', 'failed', 'intervention')),
    application_json TEXT NOT NULL CHECK (json_valid(application_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (proposal_id, platform)
);

PRAGMA user_version = 13;

COMMIT;
