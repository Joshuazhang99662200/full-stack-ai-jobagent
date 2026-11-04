BEGIN IMMEDIATE;
CREATE TABLE public_career_runs (
 run_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
 run_json TEXT NOT NULL CHECK(json_valid(run_json))
);
CREATE TABLE public_career_records (
 candidate_id TEXT NOT NULL, provider TEXT NOT NULL, board TEXT NOT NULL,
 source_job_id TEXT NOT NULL, job_id TEXT NOT NULL, run_id TEXT NOT NULL,
 record_json TEXT NOT NULL CHECK(json_valid(record_json)),
 PRIMARY KEY(candidate_id, provider, board, source_job_id)
);
CREATE TABLE public_career_http (
 receipt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
 source TEXT NOT NULL, dispatched_at TEXT NOT NULL, outcome TEXT NOT NULL,
 response BLOB, error TEXT
);
CREATE TABLE public_career_stops (
 candidate_id TEXT NOT NULL, provider TEXT NOT NULL, reason TEXT NOT NULL,
 PRIMARY KEY(candidate_id, provider)
);
PRAGMA user_version = 34;
COMMIT;
