"""Deliver exactly one approved application.

Invariants this module exists to hold:

- `Approval != Send` — the gate re-verifies approval freshness immediately before
  submitting, because artifacts can change between approving and sending.
- No bulk delivery — ``send`` takes one request and one package. There is no
  plural parameter, no loop and no comprehension anywhere in this file.
- `CAPTCHA != Retry` — login, CAPTCHA, verification, risk control, rate limiting
  and platform changes are ``USER_INTERVENTION_REQUIRED``. They are raised, never
  retried, never worked around.

Rate limiting has no dedicated ``InterventionReason``; it is reported as
``RISK_CONTROL`` because a platform throttling us is a control signal, not a
transient transport fault, and `stop-conditions.md` forbids probing it with a
slower request interval.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from jobagent.applications.approval import (
    ApplicationDigests,
    compute_digests,
    verify_approval_is_current,
)
from jobagent.applications.audit import ApplicationAuditor
from jobagent.applications.ports import ApplicationDeliverySource
from jobagent.errors import (
    ApprovalRequiredError,
    ContractValidationError,
    JobAgentError,
    StaleApprovalError,
    UnverifiedResumeVariantError,
    UserInterventionRequiredError,
)
from jobagent.schemas.applications import (
    ApplicationAudit,
    ApplicationPackage,
    DeliveryPolicy,
    DeliveryRequest,
    DeliveryResult,
    InterventionReason,
    SendResultStatus,
)

INTERVENTION_SIGNALS: Mapping[str, InterventionReason] = {
    "login": InterventionReason.LOGIN_REQUIRED,
    "captcha": InterventionReason.CAPTCHA_REQUIRED,
    "verification": InterventionReason.VERIFICATION_REQUIRED,
    "risk_control": InterventionReason.RISK_CONTROL,
    "rate_limit": InterventionReason.RISK_CONTROL,
    "platform_changed": InterventionReason.PLATFORM_CHANGED,
}

_REFUSALS = (UnverifiedResumeVariantError, ApprovalRequiredError, StaleApprovalError)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def intervention_required(signal: str, *, application_id: str) -> UserInterventionRequiredError:
    """Build the error a connector raises when a platform needs a person."""
    reason = INTERVENTION_SIGNALS.get(signal, InterventionReason.RISK_CONTROL)
    return UserInterventionRequiredError(
        "Delivery stopped: the platform requires a person on the account.",
        details={
            "application_id": application_id,
            "intervention_reason": reason.value,
            "signal": signal,
            "retryable": False,
        },
    )


def _reason_of(error: UserInterventionRequiredError) -> InterventionReason | None:
    raw = error.details.get("intervention_reason")
    return None if raw is None else InterventionReason(str(raw))


class DeliveryGate:
    """Send one approved application. Never a batch, never a retry."""

    def __init__(
        self,
        *,
        source: ApplicationDeliverySource,
        auditor: ApplicationAuditor,
        policy: DeliveryPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.source = source
        self.auditor = auditor
        self.policy = policy if policy is not None else DeliveryPolicy()
        self.clock = clock if clock is not None else _utc_now

    def send(self, request: DeliveryRequest, package: ApplicationPackage) -> DeliveryResult:
        """Deliver this one application, or refuse loudly and record the attempt."""
        if request.application_id != package.application_id:
            raise ContractValidationError(
                "Delivery request and application package describe different applications.",
                details={
                    "application_id": package.application_id,
                    "requested_application_id": request.application_id,
                },
            )
        digests = compute_digests(package, self.policy)
        self._refuse_unless_authorized(request, package, digests)
        return self._submit_once(request, package, digests)

    def _refuse_unless_authorized(
        self,
        request: DeliveryRequest,
        package: ApplicationPackage,
        digests: ApplicationDigests,
    ) -> None:
        try:
            self._check_variant(package)
            self._check_request_digests(request, digests)
            verify_approval_is_current(request.approval, digests)
        except _REFUSALS as error:
            self._audit(
                package,
                digests,
                request,
                DeliveryResult(
                    application_id=package.application_id,
                    status=SendResultStatus.FAILED,
                    attempted_at=self.clock(),
                    failure_reason=error.code,
                ),
            )
            raise

    def _check_variant(self, package: ApplicationPackage) -> None:
        report = package.resume_variant.verification
        if report.passed:
            return
        raise UnverifiedResumeVariantError(
            "Resume variant failed verification and must not be delivered.",
            details={
                "application_id": package.application_id,
                "resume_variant_id": package.resume_variant.id,
                "evidence_coverage": report.evidence_coverage,
            },
        )

    def _check_request_digests(
        self,
        request: DeliveryRequest,
        digests: ApplicationDigests,
    ) -> None:
        declared = ApplicationDigests(
            application_id=request.application_id,
            job_digest=request.job_digest,
            resume_digest=request.resume_digest,
            message_digest=request.message_digest,
            policy_digest=request.policy_digest,
        )
        if declared == digests:
            return
        raise StaleApprovalError(
            "Delivery request digests no longer describe the current artifacts.",
            details={
                "application_id": digests.application_id,
                "declared": declared.as_dict(),
                "current": digests.as_dict(),
            },
        )

    def _submit_once(
        self,
        request: DeliveryRequest,
        package: ApplicationPackage,
        digests: ApplicationDigests,
    ) -> DeliveryResult:
        try:
            result = self.source.submit_application(package)
        except UserInterventionRequiredError as error:
            reason = _reason_of(error)
            audit = self._audit(
                package,
                digests,
                request,
                DeliveryResult(
                    application_id=package.application_id,
                    status=SendResultStatus.USER_INTERVENTION_REQUIRED,
                    attempted_at=self.clock(),
                    failure_reason=error.code,
                    intervention_reason=reason,
                ),
            )
            raise self._stop_for_intervention(package, audit, reason) from error
        except JobAgentError as error:
            self._audit(
                package,
                digests,
                request,
                DeliveryResult(
                    application_id=package.application_id,
                    status=SendResultStatus.FAILED,
                    attempted_at=self.clock(),
                    failure_reason=error.code,
                ),
            )
            raise
        return self._settle(request, package, digests, result)

    def _settle(
        self,
        request: DeliveryRequest,
        package: ApplicationPackage,
        digests: ApplicationDigests,
        result: DeliveryResult,
    ) -> DeliveryResult:
        if result.application_id != package.application_id:
            raise ContractValidationError(
                "Connector reported a result for a different application.",
                details={
                    "application_id": package.application_id,
                    "reported_application_id": result.application_id,
                },
            )
        audit = self._audit(package, digests, request, result)
        if result.status is not SendResultStatus.USER_INTERVENTION_REQUIRED:
            return result
        raise self._stop_for_intervention(package, audit, result.intervention_reason)

    def _stop_for_intervention(
        self,
        package: ApplicationPackage,
        audit: ApplicationAudit,
        reason: InterventionReason | None,
    ) -> UserInterventionRequiredError:
        """Normalize every intervention into one non-retryable stop signal."""
        return UserInterventionRequiredError(
            "Delivery stopped for human intervention; JobAgent never retries this state.",
            details={
                "application_id": package.application_id,
                "intervention_reason": None if reason is None else reason.value,
                "audit_id": audit.audit_id,
                "attempt": audit.attempt,
                "retryable": False,
            },
        )

    def _audit(
        self,
        package: ApplicationPackage,
        digests: ApplicationDigests,
        request: DeliveryRequest,
        result: DeliveryResult,
    ) -> ApplicationAudit:
        return self.auditor.record_attempt(
            package=package,
            digests=digests,
            approval=request.approval,
            result=result,
        )
