from datetime import UTC, datetime, timedelta

from jobagent.jobs.ranking import JobRanker
from jobagent.schemas.job_intelligence import JobAssessment
from jobagent.schemas.jobs import (
    FilterDecision,
    FilterReason,
    HardFilterResult,
    MatchDecision,
    MatchResult,
)


def assessment(
    job_id: str,
    *,
    filter_decision: FilterDecision = FilterDecision.PASS,
    match_decision: MatchDecision = MatchDecision.STRONG_MATCH,
    overall: float = 0.8,
    must_have: float = 0.8,
    published_offset: int = 0,
) -> JobAssessment:
    reasons = (
        []
        if filter_decision is FilterDecision.PASS
        else [FilterReason(rule_id="TEST_RULE", message="Requires review or rejection.")]
    )
    return JobAssessment(
        job_id=job_id,
        filter_result=HardFilterResult(decision=filter_decision, reasons=reasons),
        match_result=MatchResult(
            overall=overall,
            decision=match_decision,
            strengths=["Explainable match."],
        ),
        published_at=datetime(2026, 8, 20, tzinfo=UTC) + timedelta(days=published_offset),
        must_have_score=must_have,
    )


def test_ranker_orders_pass_before_review_and_excludes_rejected() -> None:
    ranked = JobRanker().rank(
        [
            assessment("JOB_REVIEW", filter_decision=FilterDecision.REVIEW, overall=0.99),
            assessment("JOB_PASS", overall=0.7),
            assessment("JOB_REJECT", filter_decision=FilterDecision.REJECT, overall=1.0),
        ]
    )

    assert [item.job_id for item in ranked] == ["JOB_PASS", "JOB_REVIEW"]
    assert [item.rank for item in ranked] == [1, 2]
    assert all(not item.application_ready for item in ranked)


def test_ranker_uses_decision_score_must_have_date_then_job_id() -> None:
    ranked = JobRanker().rank(
        [
            assessment("JOB_D", match_decision=MatchDecision.POSSIBLE_MATCH, overall=0.95),
            assessment("JOB_C", overall=0.8, must_have=0.7),
            assessment("JOB_B", overall=0.8, must_have=0.8, published_offset=-1),
            assessment("JOB_A", overall=0.8, must_have=0.8, published_offset=0),
        ]
    )

    assert [item.job_id for item in ranked] == ["JOB_A", "JOB_B", "JOB_C", "JOB_D"]


def test_ranking_is_input_order_invariant() -> None:
    assessments = [assessment("JOB_B"), assessment("JOB_A")]

    forward = JobRanker().rank(assessments)
    reverse = JobRanker().rank(list(reversed(assessments)))

    assert forward == reverse
