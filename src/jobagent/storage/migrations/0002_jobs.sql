BEGIN IMMEDIATE;

CREATE TABLE normalized_jobs (
    job_id TEXT PRIMARY KEY,
    job_json TEXT NOT NULL CHECK (json_valid(job_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE job_provenance (
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (job_id, source, source_id, url, collected_at),
    FOREIGN KEY (job_id) REFERENCES normalized_jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX job_provenance_source_idx ON job_provenance(source, source_id);

CREATE TABLE job_requirements (
    job_id TEXT PRIMARY KEY,
    requirements_json TEXT NOT NULL CHECK (json_valid(requirements_json)),
    content_digest TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES normalized_jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE hard_filter_results (
    candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (candidate_id, job_id, policy_digest),
    FOREIGN KEY (candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES normalized_jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE job_matches (
    candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    requirements_digest TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        candidate_id,
        job_id,
        evidence_digest,
        requirements_digest,
        policy_digest
    ),
    FOREIGN KEY (candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES normalized_jobs(job_id) ON DELETE CASCADE
);

PRAGMA user_version = 2;
COMMIT;
