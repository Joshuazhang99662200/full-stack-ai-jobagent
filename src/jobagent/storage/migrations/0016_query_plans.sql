BEGIN IMMEDIATE;
CREATE TABLE jd_query_plans (
    plan_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    source TEXT NOT NULL,
    input_json TEXT NOT NULL CHECK (json_valid(input_json)),
    plan_json TEXT NOT NULL CHECK (json_valid(plan_json))
);
PRAGMA user_version = 16;
COMMIT;
