BEGIN IMMEDIATE;

-- Append-only record of patrol checks; the latest one paces the next.
CREATE TABLE patrol_checks (
    check_id TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL,
    check_json TEXT NOT NULL CHECK (json_valid(check_json))
);

PRAGMA user_version = 6;

COMMIT;
