"""Deterministic Candidate Core readiness reporting."""

from collections.abc import Sequence

from jobagent.candidate.gaps import GapDetector
from jobagent.schemas.candidate import (
    CandidateProfile,
    CandidateReadinessReport,
    CandidateStatus,
    Confidence,
    EvidenceItem,
    GapPriority,
)


class CandidateReadinessService:
    """Summarize known candidate data and gaps without requiring invented completeness."""

    def __init__(self, gap_detector: GapDetector | None = None) -> None:
        self.gap_detector = gap_detector or GapDetector()

    def evaluate(
        self,
        profile: CandidateProfile,
        evidence: Sequence[EvidenceItem],
        *,
        target_role: str | None = None,
    ) -> CandidateStatus:
        evidence_items = list(evidence)
        gaps = self.gap_detector.detect(profile, evidence_items, target_role=target_role)
        completeness = self._profile_completeness(profile)
        confirmed_count = sum(item.user_confirmed for item in evidence_items)
        confirmed_ratio = confirmed_count / len(evidence_items) if evidence_items else 0.0
        gap_penalty = min(
            1.0,
            sum(
                0.2
                if gap.priority is GapPriority.HIGH
                else 0.08
                if gap.priority is GapPriority.MEDIUM
                else 0.03
                for gap in gaps
            ),
        )
        target_readiness = min(
            1.0,
            0.45 * completeness + 0.45 * confirmed_ratio + 0.1 * (1.0 - gap_penalty),
        )
        readiness = CandidateReadinessReport(
            profile_completeness=round(completeness, 4),
            high_value_gaps=[gap for gap in gaps if gap.priority is GapPriority.HIGH],
            weak_claim_evidence_ids=[
                item.id for item in evidence_items if item.confidence is Confidence.WEAK
            ],
            confirmed_evidence_count=confirmed_count,
            target_role_readiness=round(target_readiness, 4),
        )
        return CandidateStatus(
            candidate_id=profile.id,
            readiness=readiness,
            open_gap_count=len(gaps),
            unconfirmed_evidence_count=sum(not item.user_confirmed for item in evidence_items),
        )

    @staticmethod
    def _profile_completeness(profile: CandidateProfile) -> float:
        score = 0.0
        score += 0.1 if profile.full_name else 0.0
        score += 0.3 if profile.experiences else 0.0
        score += 0.25 if profile.skills else 0.0
        score += 0.1 if profile.education else 0.0
        score += 0.15 if profile.achievements or profile.projects else 0.0
        score += 0.1 if profile.languages else 0.0
        unknown_factor = 1.0 - min(0.3, 0.05 * len(profile.unknown_fields))
        return score * unknown_factor
