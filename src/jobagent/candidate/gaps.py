"""Deterministic candidate gap detection."""

import re

from jobagent.schemas.candidate import (
    CandidateGap,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    GapPriority,
)

_GENERIC_ROLE_WORDS = {
    "developer",
    "engineer",
    "lead",
    "manager",
    "senior",
    "specialist",
}
_PRIORITY_ORDER = {GapPriority.HIGH: 0, GapPriority.MEDIUM: 1, GapPriority.LOW: 2}


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(token) > 1}


class GapDetector:
    """Describe missing or weak candidate knowledge without filling it in."""

    def detect(
        self,
        profile: CandidateProfile,
        evidence: list[EvidenceItem],
        *,
        target_role: str | None = None,
    ) -> list[CandidateGap]:
        gaps: list[CandidateGap] = []
        if not profile.experiences:
            gaps.append(
                CandidateGap(
                    id="GAP_EXPERIENCE",
                    field_path="experiences",
                    reason="No work or project experience has been captured.",
                    priority=GapPriority.HIGH,
                    target_role=target_role,
                    suggested_question=(
                        "Which recent role or project best shows your relevant work?"
                    ),
                )
            )
        if not profile.skills:
            gaps.append(
                CandidateGap(
                    id="GAP_SKILLS",
                    field_path="skills",
                    reason="No evidence-linked skills have been captured.",
                    priority=GapPriority.HIGH,
                    target_role=target_role,
                    suggested_question="Which skills have you applied in real work or projects?",
                )
            )
        if not profile.full_name:
            gaps.append(
                CandidateGap(
                    id="GAP_FULL_NAME",
                    field_path="full_name",
                    reason="Candidate identity is incomplete.",
                    priority=GapPriority.MEDIUM,
                    target_role=target_role,
                    suggested_question=(
                        "What full name should appear on your application materials?"
                    ),
                )
            )

        role_tokens = _tokens(target_role or "") - _GENERIC_ROLE_WORDS
        for item in evidence:
            if item.user_confirmed:
                continue
            evidence_tokens = _tokens(item.statement)
            for value in (*item.skills, *item.domains):
                evidence_tokens.update(_tokens(value))
            relevant = bool(role_tokens & evidence_tokens)
            priority = GapPriority.HIGH if relevant else GapPriority.MEDIUM
            qualifier = "weak" if item.confidence is Confidence.WEAK else "unconfirmed"
            gaps.append(
                CandidateGap(
                    id=f"GAP_{item.id}",
                    field_path=f"evidence[{item.id}]",
                    reason=(
                        f"Candidate evidence is {qualifier} and cannot support a final claim yet."
                    ),
                    priority=priority,
                    target_role=target_role,
                    suggested_question=(
                        f"Can you clarify the exact scope and outcome behind: {item.statement}"
                    ),
                )
            )

        for index, unknown in enumerate(profile.unknown_fields, start=1):
            priority = (
                GapPriority.HIGH
                if unknown.target_role_relevance >= 0.7
                else GapPriority.MEDIUM
                if unknown.target_role_relevance >= 0.3
                else GapPriority.LOW
            )
            gaps.append(
                CandidateGap(
                    id=f"GAP_UNKNOWN_{index}",
                    field_path=unknown.path,
                    reason=unknown.reason,
                    priority=priority,
                    target_role=target_role,
                    suggested_question=f"What can you confirm about {unknown.path}?",
                )
            )

        return sorted(gaps, key=lambda gap: (_PRIORITY_ORDER[gap.priority], gap.id))
