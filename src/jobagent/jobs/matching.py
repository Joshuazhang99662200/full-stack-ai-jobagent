"""Evidence admissibility and deterministic match aggregation."""

from collections.abc import Sequence

from jobagent.errors import ContractValidationError, MissingEvidenceError
from jobagent.schemas.candidate import Confidence, EvidenceItem
from jobagent.schemas.job_intelligence import (
    MatchThresholdPolicy,
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
)
from jobagent.schemas.jobs import (
    DimensionScore,
    JobRequirement,
    JobRequirementProfile,
    MatchDecision,
    MatchResult,
    RequirementPriority,
)

_PRIORITY_WEIGHT = {
    RequirementPriority.MUST: 3.0,
    RequirementPriority.PREFERRED: 2.0,
    RequirementPriority.CONTEXT: 1.0,
    RequirementPriority.UNCERTAIN: 0.5,
}
_OUTCOME_VALUE = {
    RequirementMatchOutcome.SUPPORTED: 1.0,
    RequirementMatchOutcome.PARTIAL: 0.5,
    RequirementMatchOutcome.UNCERTAIN: 0.25,
    RequirementMatchOutcome.MISSING: 0.0,
}


def admissible_evidence(evidence: Sequence[EvidenceItem]) -> list[EvidenceItem]:
    return sorted(
        (
            item
            for item in evidence
            if item.user_confirmed and item.confidence is not Confidence.WEAK
        ),
        key=lambda item: item.id,
    )


class MatchAggregator:
    """Compute explainable match scores without accepting provider-supplied totals."""

    def aggregate(
        self,
        requirements: JobRequirementProfile,
        mappings: RequirementMatchSet,
        evidence: Sequence[EvidenceItem],
        policy: MatchThresholdPolicy,
    ) -> MatchResult:
        if mappings.job_id != requirements.job_id:
            raise ContractValidationError("Requirement mappings belong to another job.")
        requirements_by_id = {item.id: item for item in requirements.requirements}
        mappings_by_id = {item.requirement_id: item for item in mappings.matches}
        if set(requirements_by_id) != set(mappings_by_id):
            raise ContractValidationError("Requirement mapping coverage is incomplete.")
        admissible_ids = {item.id for item in admissible_evidence(evidence)}
        for mapping in mappings.matches:
            if (
                mapping.outcome
                in {RequirementMatchOutcome.SUPPORTED, RequirementMatchOutcome.PARTIAL}
                and not set(mapping.evidence_ids) <= admissible_ids
            ):
                raise MissingEvidenceError(
                    "Requirement mapping cites nonadmissible evidence.",
                    details={"requirement_id": mapping.requirement_id},
                )

        if not requirements.requirements:
            return MatchResult(
                overall=0.0,
                decision=MatchDecision.NOT_A_MATCH,
                uncertainties=["No requirements were available for matching."],
            )

        total_weight = sum(_PRIORITY_WEIGHT[item.priority] for item in requirements.requirements)
        earned = sum(
            _PRIORITY_WEIGHT[requirement.priority]
            * _OUTCOME_VALUE[mappings_by_id[requirement.id].outcome]
            for requirement in requirements.requirements
        )
        overall = round(earned / total_weight, 4)
        strengths: list[str] = []
        partial_matches: list[str] = []
        hard_gaps: list[str] = []
        uncertainties: list[str] = []
        for requirement in requirements.requirements:
            outcome = mappings_by_id[requirement.id].outcome
            if outcome is RequirementMatchOutcome.SUPPORTED:
                strengths.append(requirement.statement)
            elif outcome is RequirementMatchOutcome.PARTIAL:
                partial_matches.append(requirement.statement)
            elif outcome is RequirementMatchOutcome.MISSING:
                if requirement.priority is RequirementPriority.MUST:
                    hard_gaps.append(requirement.statement)
                else:
                    partial_matches.append(f"Missing preferred: {requirement.statement}")
            else:
                uncertainties.append(requirement.statement)

        dimensions = self._dimensions(requirements.requirements, mappings_by_id)
        decision = self._decision(overall, hard_gaps, policy)
        cited_ids = sorted(
            {
                evidence_id
                for mapping in mappings.matches
                if mapping.outcome
                in {RequirementMatchOutcome.SUPPORTED, RequirementMatchOutcome.PARTIAL}
                for evidence_id in mapping.evidence_ids
            }
        )
        return MatchResult(
            overall=overall,
            decision=decision,
            dimensions=dimensions,
            strengths=strengths,
            partial_matches=partial_matches,
            hard_gaps=hard_gaps,
            uncertainties=uncertainties,
            evidence_ids=cited_ids,
        )

    @staticmethod
    def _dimensions(
        requirements: Sequence[JobRequirement],
        mappings_by_id: dict[str, RequirementEvidenceMatch],
    ) -> list[DimensionScore]:
        groups: list[tuple[str, list[JobRequirement]]] = [
            (
                "must_have",
                [item for item in requirements if item.priority is RequirementPriority.MUST],
            ),
            (
                "preferred",
                [
                    item
                    for item in requirements
                    if item.priority is RequirementPriority.PREFERRED
                ],
            ),
        ]
        for category in sorted({item.category.casefold() for item in requirements}):
            groups.append(
                (
                    category,
                    [item for item in requirements if item.category.casefold() == category],
                )
            )
        dimensions: list[DimensionScore] = []
        seen: set[str] = set()
        for name, items in groups:
            if not items or name in seen:
                continue
            seen.add(name)
            score = sum(_OUTCOME_VALUE[mappings_by_id[item.id].outcome] for item in items) / len(
                items
            )
            evidence_ids = sorted(
                {
                    evidence_id
                    for item in items
                    for evidence_id in mappings_by_id[item.id].evidence_ids
                }
            )
            dimensions.append(
                DimensionScore(
                    dimension=name,
                    score=round(score, 4),
                    explanation=f"{len(items)} requirement(s) evaluated for {name}.",
                    evidence_ids=evidence_ids,
                )
            )
        return dimensions

    @staticmethod
    def _decision(
        overall: float,
        hard_gaps: Sequence[str],
        policy: MatchThresholdPolicy,
    ) -> MatchDecision:
        if hard_gaps:
            return (
                MatchDecision.WEAK_MATCH
                if overall >= policy.weak
                else MatchDecision.NOT_A_MATCH
            )
        if overall >= policy.strong:
            return MatchDecision.STRONG_MATCH
        if overall >= policy.possible:
            return MatchDecision.POSSIBLE_MATCH
        if overall >= policy.weak:
            return MatchDecision.WEAK_MATCH
        return MatchDecision.NOT_A_MATCH
