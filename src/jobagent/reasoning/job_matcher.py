"""Structured requirement-to-evidence matching boundary."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningProvider
from jobagent.errors import InvalidProviderOutputError
from jobagent.schemas.candidate import Confidence, EvidenceItem
from jobagent.schemas.job_intelligence import (
    RequirementMatchOutcome,
    RequirementMatchSet,
)
from jobagent.schemas.jobs import JobRequirementProfile, NormalizedJob

PROMPT_ID = "job.match.evidence.v1"


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", value.casefold()))


def _is_admissible(item: EvidenceItem) -> bool:
    return item.user_confirmed and item.confidence is not Confidence.WEAK


class ReasoningJobMatcher:
    """Map requirements to candidate evidence, then enforce evidence ownership and policy."""

    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def map(
        self,
        job: NormalizedJob,
        requirements: JobRequirementProfile,
        candidate_id: str,
        evidence: Sequence[EvidenceItem],
    ) -> RequirementMatchSet:
        context: Mapping[str, Any] = {
            "job_id": job.id,
            "candidate_id": candidate_id,
            "requirements": [item.model_dump(mode="json") for item in requirements.requirements],
            "evidence": [
                {
                    **item.model_dump(mode="json"),
                    "admissible": _is_admissible(item),
                }
                for item in evidence
            ],
        }
        raw_output = self.provider.generate(
            prompt_id=PROMPT_ID,
            context=context,
            output_type=RequirementMatchSet,
        )
        mappings = self._revalidate(raw_output, job.id, candidate_id)
        self._validate_mappings(job, requirements, candidate_id, evidence, mappings)
        return mappings

    @staticmethod
    def _revalidate(
        raw_output: RequirementMatchSet,
        job_id: str,
        candidate_id: str,
    ) -> RequirementMatchSet:
        try:
            return RequirementMatchSet.model_validate(raw_output.model_dump(mode="python"))
        except (AttributeError, TypeError, ValidationError) as error:
            raise InvalidProviderOutputError(
                "Job match provider output violated the schema.",
                details={
                    "prompt_id": PROMPT_ID,
                    "job_id": job_id,
                    "candidate_id": candidate_id,
                },
            ) from error

    @staticmethod
    def _validate_mappings(
        job: NormalizedJob,
        requirements: JobRequirementProfile,
        candidate_id: str,
        evidence: Sequence[EvidenceItem],
        mappings: RequirementMatchSet,
    ) -> None:
        if mappings.job_id != job.id or requirements.job_id != job.id:
            ReasoningJobMatcher._invalid(job.id, candidate_id, "foreign job ID")
        if mappings.candidate_id != candidate_id:
            ReasoningJobMatcher._invalid(job.id, candidate_id, "foreign candidate ID")

        requirements_by_id = {item.id: item for item in requirements.requirements}
        if {item.requirement_id for item in mappings.matches} != set(requirements_by_id):
            ReasoningJobMatcher._invalid(job.id, candidate_id, "requirement coverage mismatch")
        evidence_by_id = {item.id: item for item in evidence}
        admissible_ids = {item.id for item in evidence if _is_admissible(item)}
        for mapping in mappings.matches:
            cited_ids = set(mapping.evidence_ids)
            if not cited_ids <= set(evidence_by_id):
                ReasoningJobMatcher._invalid(job.id, candidate_id, "foreign evidence ID")
            if mapping.outcome in {
                RequirementMatchOutcome.SUPPORTED,
                RequirementMatchOutcome.PARTIAL,
            }:
                if not cited_ids or not cited_ids <= admissible_ids:
                    ReasoningJobMatcher._invalid(job.id, candidate_id, "inadmissible support")
                requirement = requirements_by_id[mapping.requirement_id]
                requirement_tokens = {
                    token for keyword in requirement.keywords for token in _tokens(keyword)
                }
                if requirement_tokens:
                    evidence_tokens = {
                        token
                        for evidence_id in cited_ids
                        for value in (
                            evidence_by_id[evidence_id].statement,
                            *evidence_by_id[evidence_id].skills,
                            *evidence_by_id[evidence_id].domains,
                        )
                        for token in _tokens(value)
                    }
                    if not requirement_tokens & evidence_tokens:
                        ReasoningJobMatcher._invalid(
                            job.id,
                            candidate_id,
                            "semantic evidence mismatch",
                        )
            if mapping.outcome is RequirementMatchOutcome.MISSING and cited_ids:
                ReasoningJobMatcher._invalid(job.id, candidate_id, "missing match cites evidence")

    @staticmethod
    def _invalid(job_id: str, candidate_id: str, reason: str) -> None:
        raise InvalidProviderOutputError(
            "Job match provider output failed semantic or evidence validation.",
            details={
                "prompt_id": PROMPT_ID,
                "job_id": job_id,
                "candidate_id": candidate_id,
                "reason": reason,
            },
        )
