import json
import sqlite3

from jobagent.console.projection import snapshot
from tests.storage.test_pipeline import create, repo


def insert_match(
    database,
    candidate,
    job_id,
    score,
    *,
    stamp="2026-10-30T09:00:00+08:00",
    policy="policy-a",
    invalid=False,
):
    result = {"overall": score, "decision": "strong_match", "strengths": ["Synthetic evidence"]}
    if invalid:
        result["overall"] = "invalid"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO job_matches VALUES (?,?,?,?,?,?,?)",
            (
                candidate,
                job_id,
                "evidence-digest",
                "requirements-digest",
                policy,
                json.dumps(result),
                stamp,
            ),
        )


def test_assessments_scope_exact_identity_and_latest_instant_with_stable_tie(tmp_path):
    store = repo(tmp_path)
    job, _ = create(store)
    database = store.database.path
    insert_match(database, "CAND_OTHER", job.job_id, 1.0, policy="foreign")
    insert_match(database, job.candidate_id, "UNRELATED_JOB", 1.0, policy="unrelated")
    insert_match(
        database, job.candidate_id, job.job_id, 0.4, stamp="2026-10-30T09:00:00+08:00", policy="old"
    )
    insert_match(
        database,
        job.candidate_id,
        "JOB_DEMO_1",
        0.8,
        stamp="2026-10-30T02:00:00+00:00",
        policy="policy-a",
    )
    insert_match(
        database,
        job.candidate_id,
        "JOB_DEMO_1",
        0.9,
        stamp="2026-10-30T10:00:00+08:00",
        policy="policy-z",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO hard_filter_results VALUES(?,?,?,?,?)",
            (
                job.candidate_id,
                "JOB_DEMO_1",
                "filter-policy",
                json.dumps({"decision": "pass"}),
                "2026-10-30T10:00:00+08:00",
            ),
        )
    before = database.read_bytes()
    value = snapshot(database, tmp_path, job.candidate_id).jobs[0]
    assert value.match_result.overall == 0.9
    assert value.match_context.job_id == "JOB_DEMO_1"
    assert value.match_context.policy_digest == "policy-z"
    assert value.match_context.evidence_digest == "evidence-digest"
    assert value.match_context.updated_at.isoformat() == "2026-10-30T10:00:00+08:00"
    assert value.hard_filter_result.decision == "pass"
    assert value.hard_filter_context.policy_digest == "filter-policy"
    assert database.read_bytes() == before


def test_missing_assessment_is_unknown_and_invalid_latest_does_not_fallback(tmp_path):
    store = repo(tmp_path)
    job, _ = create(store)
    absent = snapshot(store.database.path, tmp_path, job.candidate_id)
    assert absent.jobs[0].match_result is None
    assert absent.jobs[0].hard_filter_result is None
    insert_match(store.database.path, job.candidate_id, job.job_id, 0.7, policy="valid")
    insert_match(
        store.database.path,
        job.candidate_id,
        job.job_id,
        0.9,
        policy="invalid",
        stamp="2026-10-30T11:00:00+08:00",
        invalid=True,
    )
    result = snapshot(store.database.path, tmp_path, job.candidate_id)
    assert len(result.jobs) == 1
    assert result.jobs[0].match_result is None and result.jobs[0].match_context is None
    assert next(s for s in result.sources if s.name == "assessments").status == "invalid"


def test_invalid_filter_does_not_discard_a_valid_independent_match(tmp_path):
    store = repo(tmp_path)
    job, _ = create(store)
    insert_match(store.database.path, job.candidate_id, job.job_id, 0.6)
    with sqlite3.connect(store.database.path) as connection:
        connection.execute(
            "INSERT INTO hard_filter_results VALUES(?,?,?,?,?)",
            (
                job.candidate_id,
                job.job_id,
                "filter-policy",
                json.dumps({"decision": "unknown"}),
                "2026-10-30T10:00:00+08:00",
            ),
        )
    value = snapshot(store.database.path, tmp_path, job.candidate_id)
    assert value.jobs[0].match_result.overall == 0.6
    assert value.jobs[0].hard_filter_result is None
    assert value.jobs[0].hard_filter_context is None
    assert next(s for s in value.sources if s.name == "assessments").status == "invalid"
