BEGIN IMMEDIATE;
CREATE TABLE sent_tracking_roots (
    tracking_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    creation_digest TEXT NOT NULL
);
CREATE TABLE sent_tracking_events (
    event_id TEXT PRIMARY KEY,
    tracking_id TEXT NOT NULL REFERENCES sent_tracking_roots(tracking_id),
    version INTEGER NOT NULL,
    event_json TEXT NOT NULL CHECK (json_valid(event_json)),
    UNIQUE(tracking_id, version)
);
CREATE TABLE sent_tracking_requests (
    event_id TEXT PRIMARY KEY,
    tracking_id TEXT NOT NULL REFERENCES sent_tracking_roots(tracking_id),
    input_digest TEXT NOT NULL,
    response_json TEXT NOT NULL CHECK (json_valid(response_json))
);
CREATE TABLE sent_tracking_sends (
    send_reference TEXT PRIMARY KEY,
    tracking_id TEXT NOT NULL REFERENCES sent_tracking_roots(tracking_id)
);
CREATE INDEX sent_tracking_candidate_idx ON sent_tracking_roots(candidate_id);
PRAGMA user_version = 17;
COMMIT;
