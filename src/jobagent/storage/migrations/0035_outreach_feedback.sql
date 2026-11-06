BEGIN IMMEDIATE;

-- Host-neutral provenance for owner feedback: each event judges one asked item.
CREATE TABLE outreach_feedback_links (
    event_id TEXT PRIMARY KEY REFERENCES sourcing_feedback_events(event_id),
    batch_id TEXT NOT NULL,
    ask_id TEXT NOT NULL,
    item_number INTEGER NOT NULL,
    link_json TEXT NOT NULL CHECK (json_valid(link_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE (ask_id, item_number)
);
CREATE TRIGGER outreach_feedback_links_no_update BEFORE UPDATE ON outreach_feedback_links
BEGIN SELECT RAISE(ABORT, 'feedback is append only'); END;
CREATE TRIGGER outreach_feedback_links_no_delete BEFORE DELETE ON outreach_feedback_links
BEGIN SELECT RAISE(ABORT, 'feedback is append only'); END;

PRAGMA user_version = 35;
COMMIT;
