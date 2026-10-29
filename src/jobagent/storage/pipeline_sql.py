"""Single standard form projection; field names follow the pipeline contract."""

PIPELINE_VIEW_SQL = """
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
"""
