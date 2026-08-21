"""Stable ranking for explainable Job Intelligence assessments."""

from collections.abc import Sequence
from datetime import UTC

from jobagent.errors import ContractValidationError
from jobagent.schemas.job_intelligence import JobAssessment, RankedJob
from jobagent.schemas.jobs import FilterDecision, MatchDecision

_FILTER_TIER = {
    FilterDecision.PASS: 0,
    FilterDecision.REVIEW: 1,
    FilterDecision.REJECT: 2,
}
_MATCH_TIER = {
    MatchDecision.STRONG_MATCH: 0,
    MatchDecision.POSSIBLE_MATCH: 1,
    MatchDecision.WEAK_MATCH: 2,
    MatchDecision.NOT_A_MATCH: 3,
}


class JobRanker:
    """Order assessments without changing their filter or match decisions."""

    def rank(
        self,
        assessments: Sequence[JobAssessment],
        *,
        include_rejected: bool = False,
    ) -> list[RankedJob]:
        job_ids = [assessment.job_id for assessment in assessments]
        if len(set(job_ids)) != len(job_ids):
            raise ContractValidationError("Job assessments must have unique job IDs.")
        eligible = [
            assessment
            for assessment in assessments
            if include_rejected or assessment.filter_result.decision is not FilterDecision.REJECT
        ]
        ordered = sorted(eligible, key=self._sort_key)
        return [
            RankedJob(
                job_id=assessment.job_id,
                rank=index,
                filter_decision=assessment.filter_result.decision,
                match_decision=assessment.match_result.decision,
                overall=assessment.match_result.overall,
                must_have_score=assessment.must_have_score,
                application_ready=False,
                explanation=(
                    f"filter={assessment.filter_result.decision.value}; "
                    f"match={assessment.match_result.decision.value}; "
                    f"overall={assessment.match_result.overall:.4f}"
                ),
            )
            for index, assessment in enumerate(ordered, start=1)
        ]

    @staticmethod
    def _sort_key(assessment: JobAssessment) -> tuple[int, int, float, float, float, str]:
        published = assessment.published_at
        if published is None:
            published_timestamp = float("-inf")
        else:
            aware = published if published.tzinfo is not None else published.replace(tzinfo=UTC)
            published_timestamp = aware.timestamp()
        return (
            _FILTER_TIER[assessment.filter_result.decision],
            _MATCH_TIER[assessment.match_result.decision],
            -assessment.match_result.overall,
            -assessment.must_have_score,
            -published_timestamp,
            assessment.job_id,
        )
