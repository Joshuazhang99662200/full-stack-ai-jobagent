BEGIN IMMEDIATE;

-- Every board message list a patrol read, kept whole so later checks can diff it.
CREATE TABLE patrol_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json))
);
CREATE INDEX patrol_snapshots_by_platform ON patrol_snapshots (platform, captured_at);

PRAGMA user_version = 8;

COMMIT;
