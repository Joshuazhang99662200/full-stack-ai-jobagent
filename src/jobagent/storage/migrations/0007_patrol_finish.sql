BEGIN IMMEDIATE;

-- A check is finished by a separate row, so the start row is never rewritten.
CREATE TABLE patrol_finishes (
    check_id TEXT PRIMARY KEY REFERENCES patrol_checks(check_id),
    finished_at TEXT NOT NULL
);

PRAGMA user_version = 7;

COMMIT;
