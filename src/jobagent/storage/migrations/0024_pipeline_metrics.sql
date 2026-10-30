BEGIN IMMEDIATE;
CREATE TABLE pipeline_stage_metrics (
    dimension_platform TEXT NOT NULL,
    dimension_domain TEXT,
    dimension_scenario TEXT,
    dimension_tech TEXT,
    dimension_greeting_version TEXT,
    dimension_resume_version TEXT,
    dimension_salary_band TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    metric_id TEXT PRIMARY KEY,
    stage_from TEXT NOT NULL,
    stage_to TEXT NOT NULL,
    numerator INTEGER NOT NULL,
    denominator INTEGER NOT NULL,
    historical_rate TEXT,
    sliced_cumulative_rate TEXT,
    optimized_rate TEXT,
    window_rate TEXT,
    sample_count INTEGER NOT NULL,
    diagnosis_id TEXT
);
CREATE TABLE pipeline_diagnoses (
    dimension_platform TEXT NOT NULL,
    dimension_domain TEXT,
    dimension_scenario TEXT,
    dimension_tech TEXT,
    dimension_greeting_version TEXT,
    dimension_resume_version TEXT,
    dimension_salary_band TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    diagnosis_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    stage_from TEXT NOT NULL,
    stage_to TEXT NOT NULL,
    historical_rate TEXT,
    sliced_cumulative_rate TEXT,
    optimized_rate TEXT,
    numerator INTEGER NOT NULL,
    denominator INTEGER NOT NULL,
    excluded_counts TEXT NOT NULL CHECK(json_valid(excluded_counts)),
    diagnosis_code TEXT NOT NULL,
    evidence_references TEXT NOT NULL CHECK(json_valid(evidence_references)),
    source_digest TEXT NOT NULL,
    rule_id TEXT,
    pre_rule_cumulative_rate TEXT
);
CREATE TABLE pipeline_metric_context (
    metric_id TEXT PRIMARY KEY REFERENCES pipeline_stage_metrics(metric_id),
    candidate_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    request_json TEXT NOT NULL CHECK(json_valid(request_json))
);
CREATE TABLE pipeline_diagnosis_reports (
    report_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    report_json TEXT NOT NULL CHECK(json_valid(report_json)),
    recorded_at TEXT NOT NULL
);
CREATE TRIGGER pipeline_stage_metrics_no_update BEFORE UPDATE ON pipeline_stage_metrics BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_stage_metrics_no_delete BEFORE DELETE ON pipeline_stage_metrics BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_metric_context_no_update BEFORE UPDATE ON pipeline_metric_context BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_metric_context_no_delete BEFORE DELETE ON pipeline_metric_context BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_diagnoses_no_update BEFORE UPDATE ON pipeline_diagnoses BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_diagnoses_no_delete BEFORE DELETE ON pipeline_diagnoses BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_diagnosis_reports_no_update BEFORE UPDATE ON pipeline_diagnosis_reports BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
CREATE TRIGGER pipeline_diagnosis_reports_no_delete BEFORE DELETE ON pipeline_diagnosis_reports BEGIN SELECT RAISE(ABORT, 'Append-only pipeline analysis'); END;
PRAGMA user_version = 24;
COMMIT;
