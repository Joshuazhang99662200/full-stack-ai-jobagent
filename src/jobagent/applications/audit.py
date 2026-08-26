"""Record every delivery attempt, especially the ones that did not succeed.

Per `skills/job-hunting/references/audit-feedback.md` an audit stores artifact
IDs, digests, the attempt number, the outcome and a timestamp. It never copies
resume text, message text or a provider payload: recovery goes through the IDs.

An attempt that never happened produces no audit record.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from jobagent.applications.approval import ApplicationDigests
from jobagent.applications.ports import ApplicationAuditRepository
from jobagent.schemas.applications import (
    ApplicationAudit,
    ApplicationPackage,
    ApprovalRecord,
    DeliveryResult,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ApplicationAuditor:
    """Append one immutable record per delivery attempt for one application."""

    def __init__(
        self,
        repository: ApplicationAuditRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock if clock is not None else _utc_now

    def record_attempt(
        self,
        *,
        package: ApplicationPackage,
        digests: ApplicationDigests,
        approval: ApprovalRecord | None,
        result: DeliveryResult,
    ) -> ApplicationAudit:
        attempt = self.repository.next_attempt(package.application_id)
        audit = ApplicationAudit(
            audit_id=_derive_audit_id(package.application_id, attempt),
            application_id=package.application_id,
            job_id=package.job.id,
            platform=package.job.source,
            resume_variant_id=package.resume_variant.id,
            resume_digest=digests.resume_digest,
            message_digest=digests.message_digest,
            approval_id=None if approval is None else approval.approval_id,
            attempt=attempt,
            result=result.status,
            timestamp=result.attempted_at,
            failure_reason=result.failure_reason,
            intervention_reason=result.intervention_reason,
        )
        self.repository.append_audit(audit)
        return audit

    def list_audits(self, application_id: str | None = None) -> list[ApplicationAudit]:
        return list(self.repository.list_audits(application_id))


def _derive_audit_id(application_id: str, attempt: int) -> str:
    return f"AUDIT_{application_id.removeprefix('APP_')}_{attempt:04d}"
