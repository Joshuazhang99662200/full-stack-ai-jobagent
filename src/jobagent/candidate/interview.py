"""One-question-at-a-time adaptive candidate interview."""

from collections.abc import Collection, Sequence
from datetime import datetime

from jobagent.errors import ContractValidationError
from jobagent.schemas.candidate import (
    CandidateGap,
    Confidence,
    EvidenceItem,
    EvidenceType,
    GapPriority,
    InterviewAnswer,
    InterviewEvent,
    InterviewEventType,
    InterviewOutcome,
    InterviewQuestion,
)
from jobagent.schemas.common import SourceReference, SourceType

_PRIORITY_SCORE = {GapPriority.HIGH: 0.6, GapPriority.MEDIUM: 0.4, GapPriority.LOW: 0.2}


class AdaptiveInterview:
    """Select one useful gap and turn a human response into draft evidence."""

    def next_question(
        self,
        candidate_id: str,
        gaps: Sequence[CandidateGap],
        *,
        target_role: str | None = None,
        recent_gap_ids: Collection[str] = (),
    ) -> InterviewQuestion | None:
        eligible = [gap for gap in gaps if gap.id not in recent_gap_ids]
        if not eligible:
            return None

        ranked = sorted(
            eligible,
            key=lambda gap: (-self._score(gap, target_role), gap.id),
        )
        selected = ranked[0]
        score = self._score(selected, target_role)
        return InterviewQuestion(
            id=f"QUESTION_{selected.id.removeprefix('GAP_')}",
            candidate_id=candidate_id,
            primary_gap_id=selected.id,
            text=(
                selected.suggested_question or f"What can you confirm about {selected.field_path}?"
            ),
            reason=selected.reason,
            expected_information=f"Verified detail for {selected.field_path}",
            score=score,
        )

    def record_answer(
        self,
        question: InterviewQuestion,
        answer: InterviewAnswer,
        *,
        evidence_id: str,
        event_id: str,
        created_at: datetime,
    ) -> InterviewOutcome:
        if answer.question_id != question.id:
            raise ContractValidationError(
                "Interview answer does not match the selected question.",
                details={"question_id": question.id, "answer_question_id": answer.question_id},
            )

        if answer.skipped:
            event = InterviewEvent(
                id=event_id,
                candidate_id=question.candidate_id,
                event_type=InterviewEventType.SKIP,
                question_id=question.id,
                payload={"primary_gap_id": question.primary_gap_id},
                created_at=created_at,
            )
            return InterviewOutcome(event=event)

        assert answer.answer is not None
        draft_evidence = EvidenceItem(
            id=evidence_id,
            type=self._evidence_type(question),
            statement=answer.answer,
            source=SourceReference(
                type=SourceType.INTERVIEW,
                reference=f"{question.id}:answer",
            ),
            confidence=Confidence.EXPLICIT,
            user_confirmed=False,
        )
        event = InterviewEvent(
            id=event_id,
            candidate_id=question.candidate_id,
            event_type=InterviewEventType.ANSWER,
            question_id=question.id,
            payload={
                "primary_gap_id": question.primary_gap_id,
                "evidence_id": draft_evidence.id,
            },
            created_at=created_at,
        )
        return InterviewOutcome(event=event, draft_evidence=draft_evidence)

    @staticmethod
    def _score(gap: CandidateGap, target_role: str | None) -> float:
        role_bonus = 0.2 if target_role and gap.target_role == target_role else 0.0
        information_gain = 0.15 if gap.field_path.startswith("experience") else 0.1
        return min(1.0, _PRIORITY_SCORE[gap.priority] + role_bonus + information_gain)

    @staticmethod
    def _evidence_type(question: InterviewQuestion) -> EvidenceType:
        path = question.expected_information.lower()
        if "skill" in path:
            return EvidenceType.SKILL
        if "education" in path:
            return EvidenceType.EDUCATION
        if "management" in path:
            return EvidenceType.MANAGEMENT
        return EvidenceType.EXPERIENCE
