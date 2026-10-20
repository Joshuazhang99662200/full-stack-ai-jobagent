from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from jobagent.candidate.interview import AdaptiveInterview
from jobagent.errors import ContractValidationError
from jobagent.schemas.candidate import (
    CandidateGap,
    GapPriority,
    InterviewAnswer,
    InterviewEventType,
    MetricFact,
)
from jobagent.schemas.common import SourceType


def gap(gap_id: str, priority: GapPriority, question: str) -> CandidateGap:
    return CandidateGap(
        id=gap_id,
        field_path="experiences",
        reason="More evidence is needed.",
        priority=priority,
        target_role="Python Engineer",
        suggested_question=question,
    )


def test_next_question_returns_only_highest_scoring_nonrepeated_gap() -> None:
    interview = AdaptiveInterview()
    gaps = [
        gap("GAP_HIGH", GapPriority.HIGH, "Describe your strongest project."),
        gap("GAP_MEDIUM", GapPriority.MEDIUM, "Describe another project."),
    ]

    question = interview.next_question(
        "CAND_001",
        gaps,
        target_role="Python Engineer",
        recent_gap_ids={"GAP_HIGH"},
    )

    assert question is not None
    assert question.primary_gap_id == "GAP_MEDIUM"
    assert question.text == "Describe another project."


def test_next_question_returns_none_without_open_gaps() -> None:
    assert AdaptiveInterview().next_question("CAND_001", []) is None


def test_answer_creates_unconfirmed_interview_evidence() -> None:
    interview = AdaptiveInterview()
    question = interview.next_question(
        "CAND_001",
        [gap("GAP_HIGH", GapPriority.HIGH, "Describe your strongest project.")],
    )
    assert question is not None

    outcome = interview.record_answer(
        question,
        InterviewAnswer(
            question_id=question.id,
            answer="I designed and implemented the internal API.",
        ),
        evidence_id="EVID_INTERVIEW_001",
        event_id="EVENT_001",
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    assert outcome.event.event_type is InterviewEventType.ANSWER
    assert outcome.draft_evidence is not None
    assert outcome.draft_evidence.statement == "I designed and implemented the internal API."
    assert outcome.draft_evidence.source.type is SourceType.INTERVIEW
    assert not outcome.draft_evidence.user_confirmed


def test_answer_metrics_are_carried_onto_draft_evidence() -> None:
    interview = AdaptiveInterview()
    question = interview.next_question(
        "CAND_001",
        [gap("GAP_HIGH", GapPriority.HIGH, "Describe your strongest project.")],
    )
    assert question is not None

    outcome = interview.record_answer(
        question,
        InterviewAnswer(
            question_id=question.id,
            answer="Revision rate fell from 70% to 26%; the product reached 1,000+ founders.",
            metrics=[
                MetricFact(name="revision rate after", value=Decimal("26"), unit="%"),
                MetricFact(name="founders reached", value=Decimal("1000"), unit="people"),
            ],
        ),
        evidence_id="EVID_INTERVIEW_002",
        event_id="EVENT_004",
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    assert outcome.draft_evidence is not None
    assert [metric.value for metric in outcome.draft_evidence.metrics] == [
        Decimal("26"),
        Decimal("1000"),
    ]
    assert not outcome.draft_evidence.user_confirmed


def test_answer_metric_value_must_be_stated_in_the_answer() -> None:
    with pytest.raises(ValidationError, match="not stated in the answer"):
        InterviewAnswer(
            question_id="QUESTION_001",
            answer="Revision rate fell sharply.",
            metrics=[MetricFact(name="revision rate after", value=Decimal("26"), unit="%")],
        )


def test_skipped_answer_cannot_carry_metrics() -> None:
    with pytest.raises(ValidationError, match="skipped"):
        InterviewAnswer(
            question_id="QUESTION_001",
            skipped=True,
            metrics=[MetricFact(name="revision rate after", value=Decimal("26"), unit="%")],
        )


def test_skipped_answer_creates_event_without_evidence() -> None:
    interview = AdaptiveInterview()
    question = interview.next_question(
        "CAND_001",
        [gap("GAP_HIGH", GapPriority.HIGH, "Describe your strongest project.")],
    )
    assert question is not None

    outcome = interview.record_answer(
        question,
        InterviewAnswer(question_id=question.id, skipped=True),
        evidence_id="EVID_UNUSED",
        event_id="EVENT_002",
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    assert outcome.event.event_type is InterviewEventType.SKIP
    assert outcome.draft_evidence is None


def test_answer_must_match_question() -> None:
    interview = AdaptiveInterview()
    question = interview.next_question(
        "CAND_001",
        [gap("GAP_HIGH", GapPriority.HIGH, "Describe your strongest project.")],
    )
    assert question is not None

    with pytest.raises(ContractValidationError, match="does not match"):
        interview.record_answer(
            question,
            InterviewAnswer(question_id="QUESTION_OTHER", answer="Answer"),
            evidence_id="EVID_INTERVIEW_001",
            event_id="EVENT_003",
            created_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
