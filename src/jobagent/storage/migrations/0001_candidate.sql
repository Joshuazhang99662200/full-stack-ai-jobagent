BEGIN IMMEDIATE;

CREATE TABLE candidate_profiles (
    candidate_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL CHECK (json_valid(profile_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE evidence_items (
    evidence_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE
);

CREATE INDEX evidence_items_candidate_idx ON evidence_items(candidate_id);

CREATE TABLE resume_ingestions (
    resume_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    resume_json TEXT NOT NULL CHECK (json_valid(resume_json)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE
);

CREATE INDEX resume_ingestions_candidate_idx ON resume_ingestions(candidate_id);

CREATE TABLE interview_events (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('question', 'answer', 'skip')),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE
);

CREATE INDEX interview_events_candidate_idx ON interview_events(candidate_id, created_at);

PRAGMA user_version = 1;
COMMIT;
