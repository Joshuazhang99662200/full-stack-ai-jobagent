BEGIN IMMEDIATE;
CREATE TABLE pipeline_jobs (
    pipeline_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('boss', 'zhaopin')),
    job_url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    salary_raw TEXT NOT NULL,
    salary_min_k INTEGER,
    salary_max_k INTEGER,
    salary_verified TEXT NOT NULL CHECK(salary_verified IN ('pass', 'fail', 'review')),
    jd_text TEXT,
    jd_text_hash TEXT,
    jd_points TEXT,
    draft_greeting TEXT,
    draft_version TEXT,
    draft_digest TEXT,
    sent_greeting TEXT,
    sent_text_hash TEXT,
    sent_at TEXT,
    send_readback TEXT,
    resume_requested INTEGER NOT NULL DEFAULT 0 CHECK(resume_requested IN (0,1)),
    resume_requested_at TEXT,
    resume_request_evidence TEXT,
    resume_version TEXT,
    resume_file_id TEXT,
    resume_sent_at TEXT,
    pipeline_state TEXT NOT NULL CHECK(pipeline_state IN (
      'draft_pending','greeting_sent','greeting_read','initial_contact','resume_requested',
      'resume_sent','interview_pending','interviewed','abandoned')),
    state_reason TEXT CHECK(state_reason IS NULL OR state_reason IN (
      'normal','read_no_reply_2d','no_reply_2d','employer_rejected','job_closed','user_abandoned')),
    state_changed_at TEXT NOT NULL,
    entered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX pipeline_one_active_job ON pipeline_jobs(candidate_id, job_id)
WHERE pipeline_state != 'abandoned';
CREATE TABLE pipeline_authorities (
    candidate_id TEXT PRIMARY KEY,
    activated_at TEXT NOT NULL,
    evidence_reference TEXT NOT NULL
);
CREATE TABLE pipeline_meta (
    pipeline_id TEXT PRIMARY KEY REFERENCES pipeline_jobs(pipeline_id),
    meta_json TEXT NOT NULL CHECK(json_valid(meta_json))
);
CREATE TABLE pipeline_state_history (
    history_id TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL REFERENCES pipeline_jobs(pipeline_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    reason_code TEXT NOT NULL
);
CREATE TABLE pipeline_requests (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL REFERENCES pipeline_jobs(pipeline_id),
    input_digest TEXT NOT NULL,
    response_json TEXT NOT NULL CHECK(json_valid(response_json))
);
CREATE TABLE pipeline_observations (
    event_id TEXT PRIMARY KEY REFERENCES pipeline_requests(event_id),
    pipeline_id TEXT NOT NULL REFERENCES pipeline_jobs(pipeline_id),
    observed_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    observation_json TEXT NOT NULL CHECK(json_valid(observation_json))
);
CREATE TABLE pipeline_used_sends (
    send_reference TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL REFERENCES pipeline_jobs(pipeline_id),
    event_id TEXT NOT NULL
);
CREATE TABLE pipeline_rejections (
    rejection_id TEXT PRIMARY KEY,
    pipeline_id TEXT,
    candidate_id TEXT,
    occurred_at TEXT NOT NULL,
    reason_code TEXT NOT NULL
);

CREATE VIEW pipeline_job_form AS
SELECT
  p.pipeline_id, p.candidate_id, p.job_id, p.platform, p.job_url,
  p.title, p.company, p.location,
  p.salary_raw, p.salary_min_k, p.salary_max_k, p.salary_verified,
  p.jd_text, p.jd_text_hash, p.jd_points,
  p.draft_greeting, p.draft_version, p.draft_digest,
  p.sent_greeting, p.sent_text_hash, p.sent_at, p.send_readback,
  p.resume_requested, p.resume_requested_at, p.resume_request_evidence,
  p.resume_version, p.resume_file_id, p.resume_sent_at,
  p.pipeline_state, p.state_reason, p.state_changed_at,
  p.entered_at, p.updated_at
FROM pipeline_jobs p;
CREATE TRIGGER pipeline_state_history_no_update BEFORE UPDATE ON pipeline_state_history BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_state_history_no_delete BEFORE DELETE ON pipeline_state_history BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_requests_no_update BEFORE UPDATE ON pipeline_requests BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_requests_no_delete BEFORE DELETE ON pipeline_requests BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_observations_no_update BEFORE UPDATE ON pipeline_observations BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_observations_no_delete BEFORE DELETE ON pipeline_observations BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_used_sends_no_update BEFORE UPDATE ON pipeline_used_sends BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_used_sends_no_delete BEFORE DELETE ON pipeline_used_sends BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_rejections_no_update BEFORE UPDATE ON pipeline_rejections BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
CREATE TRIGGER pipeline_rejections_no_delete BEFORE DELETE ON pipeline_rejections BEGIN SELECT RAISE(ABORT, 'Append-only pipeline evidence'); END;
PRAGMA user_version = 22;
COMMIT;
