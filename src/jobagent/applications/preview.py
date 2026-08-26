"""Assemble one reviewable application package.

`Preview != Approval`. This module produces something a person can read; it never
records a decision. It also refuses to build a package around a resume variant
that failed its quality gates, because a reviewer must never be asked to approve
an artifact that already lost.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError, UnverifiedResumeVariantError
from jobagent.schemas.applications import ApplicationPackage
from jobagent.schemas.jobs import MatchResult, NormalizedJob
from jobagent.schemas.optimizer import ResumeVariant


class ApplicationPreviewService:
    """Build exactly one package from artifacts that already passed their gates."""

    def prepare(
        self,
        *,
        application_id: str,
        job: NormalizedJob,
        match: MatchResult,
        resume_variant: ResumeVariant,
        message: str,
        risks: Sequence[str] = (),
        prepared_at: datetime | None = None,
    ) -> ApplicationPackage:
        """Return a reviewable package, or refuse with a typed error."""
        self._require_same_job(application_id, job, resume_variant)
        self._require_verified_variant(application_id, resume_variant)
        text = message.strip()
        if not text:
            raise ContractValidationError(
                "Application message must not be empty.",
                details={"application_id": application_id, "field": "message"},
            )
        try:
            return ApplicationPackage(
                application_id=application_id,
                job=job,
                match=match,
                resume_variant=resume_variant,
                message=text,
                risks=list(risks),
                prepared_at=prepared_at if prepared_at is not None else datetime.now(UTC),
            )
        except ValidationError as error:
            raise ContractValidationError(
                "Application package does not satisfy its contract.",
                details={
                    "application_id": application_id,
                    "fields": sorted(
                        {str(item["loc"][0]) for item in error.errors() if item["loc"]}
                    ),
                },
            ) from error

    def _require_same_job(
        self,
        application_id: str,
        job: NormalizedJob,
        resume_variant: ResumeVariant,
    ) -> None:
        if resume_variant.target_job_id != job.id:
            raise ContractValidationError(
                "Resume variant was tailored for another job.",
                details={
                    "application_id": application_id,
                    "job_id": job.id,
                    "target_job_id": resume_variant.target_job_id,
                },
            )

    def _require_verified_variant(
        self,
        application_id: str,
        resume_variant: ResumeVariant,
    ) -> None:
        report = resume_variant.verification
        if report.passed:
            return
        raise UnverifiedResumeVariantError(
            "Resume variant failed verification and must not be offered for approval.",
            details={
                "application_id": application_id,
                "resume_variant_id": resume_variant.id,
                "unsupported_claims": report.unsupported_claims,
                "contradicted_claims": report.contradicted_claims,
                "unsupported_metrics": report.unsupported_metrics,
                "semantic_exaggerations": report.semantic_exaggerations,
                "evidence_coverage": report.evidence_coverage,
                "issue_codes": sorted({issue.code for issue in report.issues}),
            },
        )
