"""Structured JD requirement extraction boundary."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningProvider
from jobagent.errors import InvalidProviderOutputError
from jobagent.schemas.jobs import JobRequirementProfile, NormalizedJob

PROMPT_ID = "job.requirements.extract.v1"


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


class ReasoningJobRequirementExtractor:
    """Extract atomic requirements and verify their exact JD provenance."""

    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def extract(self, job: NormalizedJob) -> JobRequirementProfile:
        context: Mapping[str, Any] = {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "jd_raw": job.jd_raw,
        }
        raw_output = self.provider.generate(
            prompt_id=PROMPT_ID,
            context=context,
            output_type=JobRequirementProfile,
        )
        profile = self._revalidate(raw_output, job.id)
        self._validate_job_binding(job, profile)
        return profile

    @staticmethod
    def _revalidate(
        raw_output: JobRequirementProfile,
        job_id: str,
    ) -> JobRequirementProfile:
        try:
            return JobRequirementProfile.model_validate(raw_output.model_dump(mode="python"))
        except (AttributeError, TypeError, ValidationError) as error:
            raise InvalidProviderOutputError(
                "Job requirement provider output violated the schema.",
                details={"prompt_id": PROMPT_ID, "job_id": job_id},
            ) from error

    @staticmethod
    def _validate_job_binding(job: NormalizedJob, profile: JobRequirementProfile) -> None:
        if profile.job_id != job.id:
            ReasoningJobRequirementExtractor._invalid(job.id, "foreign job ID")
        if not profile.requirements:
            ReasoningJobRequirementExtractor._invalid(job.id, "empty requirement list")
        requirement_ids = [requirement.id for requirement in profile.requirements]
        if len(set(requirement_ids)) != len(requirement_ids):
            ReasoningJobRequirementExtractor._invalid(job.id, "duplicate requirement IDs")

        normalized_jd = _normalized(job.jd_raw)
        atomic_text = {
            _normalized(value)
            for requirement in profile.requirements
            for value in (requirement.statement, requirement.source_span)
        }
        for requirement in profile.requirements:
            if _normalized(requirement.source_span) not in normalized_jd:
                ReasoningJobRequirementExtractor._invalid(job.id, "source span not found")

        aggregate_groups = (
            profile.must_have,
            profile.nice_to_have,
            profile.responsibilities,
            profile.skills,
            profile.domains,
            profile.management,
            profile.commercial,
            profile.education,
            profile.languages,
            profile.location_constraints,
            profile.risk_signals,
        )
        for group in aggregate_groups:
            for value in group:
                normalized_value = _normalized(value)
                if not any(normalized_value in text for text in atomic_text):
                    ReasoningJobRequirementExtractor._invalid(
                        job.id,
                        "aggregate statement lacks atomic requirement",
                    )

    @staticmethod
    def _invalid(job_id: str, reason: str) -> None:
        raise InvalidProviderOutputError(
            "Job requirement provider output failed provenance validation.",
            details={"prompt_id": PROMPT_ID, "job_id": job_id, "reason": reason},
        )
