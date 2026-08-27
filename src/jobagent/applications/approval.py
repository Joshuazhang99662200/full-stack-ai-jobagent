"""Digest-bound human approval.

`Approval != Send`. Approving records that a person read this exact job, this
exact resume variant, this exact message and these exact delivery rules. If any
of the four changes afterwards the approval is stale and delivery must fail.

Digests are computed over content only. Production timestamps (`prepared_at`,
`generated_at`, `collected_at`) are stripped before hashing so that re-emitting
the same artifacts yields the same digest, while editing a single character does
not.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jobagent.errors import (
    ApprovalRequiredError,
    ContractValidationError,
    StaleApprovalError,
    UnverifiedResumeVariantError,
)
from jobagent.schemas.applications import (
    ApplicationPackage,
    ApprovalChannel,
    ApprovalRecord,
    ApprovalRequest,
    DeliveryPolicy,
)
from jobagent.schemas.common import ContractModel

_PRODUCTION_TIMESTAMPS = frozenset({"prepared_at", "generated_at", "collected_at"})
_DIGEST_LANES = ("job_digest", "resume_digest", "message_digest", "policy_digest")


def _content_only(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _content_only(item)
            for key, item in value.items()
            if key not in _PRODUCTION_TIMESTAMPS
        }
    if isinstance(value, list):
        return [_content_only(item) for item in value]
    return value


def _digest_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _digest_model(value: ContractModel) -> str:
    canonical = json.dumps(
        _content_only(value.model_dump(mode="json")),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _digest_text(canonical)


@dataclass(frozen=True, slots=True)
class ApplicationDigests:
    """The four digests an approval binds together, for exactly one application."""

    application_id: str
    job_digest: str
    resume_digest: str
    message_digest: str
    policy_digest: str

    def as_dict(self) -> dict[str, str]:
        return {
            "job_digest": self.job_digest,
            "resume_digest": self.resume_digest,
            "message_digest": self.message_digest,
            "policy_digest": self.policy_digest,
        }


def compute_digests(
    package: ApplicationPackage,
    policy: DeliveryPolicy | None = None,
) -> ApplicationDigests:
    """Digest one package deterministically. Identical content, identical output."""
    return ApplicationDigests(
        application_id=package.application_id,
        job_digest=_digest_model(package.job),
        resume_digest=_digest_model(package.resume_variant),
        message_digest=_digest_text(package.message),
        policy_digest=_digest_model(policy if policy is not None else DeliveryPolicy()),
    )


def verify_approval_is_current(
    approval: ApprovalRecord,
    digests: ApplicationDigests,
) -> None:
    """Raise unless this approval still covers these exact artifacts."""
    if approval.application_id != digests.application_id:
        raise ApprovalRequiredError(
            "No human approval exists for this application.",
            details={
                "application_id": digests.application_id,
                "approved_application_id": approval.application_id,
            },
        )
    if approval.matches(**digests.as_dict()):
        return
    approved = {lane: getattr(approval, lane) for lane in _DIGEST_LANES}
    current = digests.as_dict()
    raise StaleApprovalError(
        "Approval no longer matches the current job, resume, message and policy.",
        details={
            "application_id": digests.application_id,
            "approval_id": approval.approval_id,
            "changed": [lane for lane in _DIGEST_LANES if approved[lane] != current[lane]],
            "approved": approved,
            "current": current,
        },
    )


class ApplicationApprovalService:
    """Mint the one record that authorizes a single later delivery attempt."""

    def ask(
        self,
        package: ApplicationPackage,
        policy: DeliveryPolicy | None = None,
        *,
        asked_at: datetime | None = None,
    ) -> ApprovalRequest:
        """Pose the decision to a person, bound to exactly these artifacts.

        Asking approves nothing. It exists so a relayed approval has something that
        provably came before it, which is the part a planner must not skip: it may
        carry a person's answer, never predict one.
        """
        digests = compute_digests(package, policy)
        return ApprovalRequest(
            request_id=f"ASK_{package.application_id.removeprefix('APP_')}",
            application_id=package.application_id,
            job_digest=digests.job_digest,
            resume_digest=digests.resume_digest,
            message_digest=digests.message_digest,
            policy_digest=digests.policy_digest,
            question=(
                f"Approve delivering to {package.job.company} · {package.job.title}? "
                f"resume={package.resume_variant.id} url={package.job.url}"
            ),
            asked_at=asked_at if asked_at is not None else datetime.now(UTC),
        )

    def approve(
        self,
        package: ApplicationPackage,
        policy: DeliveryPolicy | None = None,
        *,
        confirmed: bool,
        approval_id: str | None = None,
        approved_at: datetime | None = None,
        channel: ApprovalChannel = ApprovalChannel.INTERACTIVE_TERMINAL,
        attestation: str = "",
        request: ApprovalRequest | None = None,
    ) -> ApprovalRecord:
        """Return an approval, or refuse. ``confirmed`` must come from a person."""
        if not confirmed:
            raise ApprovalRequiredError(
                "Approval requires an explicit human confirmation.",
                details={"application_id": package.application_id},
            )
        if channel is ApprovalChannel.AGENT_RELAY:
            self._check_relayed_answer(package, policy, attestation, request)
        report = package.resume_variant.verification
        if not report.passed:
            raise UnverifiedResumeVariantError(
                "Resume variant failed verification and cannot be approved.",
                details={
                    "application_id": package.application_id,
                    "resume_variant_id": package.resume_variant.id,
                    "evidence_coverage": report.evidence_coverage,
                },
            )
        digests = compute_digests(package, policy)
        try:
            return ApprovalRecord(
                approval_id=approval_id or _derive_approval_id(package.application_id),
                application_id=package.application_id,
                approved_at=approved_at if approved_at is not None else datetime.now(UTC),
                approved_by="human",
                job_digest=digests.job_digest,
                resume_digest=digests.resume_digest,
                message_digest=digests.message_digest,
                policy_digest=digests.policy_digest,
                channel=channel,
                attestation=attestation.strip(),
                request_id=request.request_id if request is not None else None,
            )
        except ValueError as error:
            raise ContractValidationError(
                "Approval record does not satisfy its contract.",
                details={"application_id": package.application_id},
            ) from error

    @staticmethod
    def _check_relayed_answer(
        package: ApplicationPackage,
        policy: DeliveryPolicy | None,
        attestation: str,
        request: ApprovalRequest | None,
    ) -> None:
        """Refuse any relayed decision the person was never actually asked for."""
        if request is None:
            raise ApprovalRequiredError(
                "A relayed approval must answer a question that was posed first.",
                details={
                    "application_id": package.application_id,
                    "why": "a planner must not decide before it holds the person's answer",
                },
            )
        if not attestation.strip():
            raise ApprovalRequiredError(
                "A relayed approval must carry the person's own answer.",
                details={"application_id": package.application_id},
            )
        if request.application_id != package.application_id:
            raise ApprovalRequiredError(
                "The question that was asked was about a different application.",
                details={
                    "application_id": package.application_id,
                    "asked_about": request.application_id,
                },
            )
        digests = compute_digests(package, policy)
        asked = {lane: getattr(request, lane) for lane in _DIGEST_LANES}
        current = digests.as_dict()
        if asked != current:
            raise ApprovalRequiredError(
                "The artifacts changed after the question was asked, so the answer "
                "was about something else.",
                details={
                    "application_id": package.application_id,
                    "request_id": request.request_id,
                    "changed": [lane for lane in _DIGEST_LANES if asked[lane] != current[lane]],
                },
            )


def _derive_approval_id(application_id: str) -> str:
    return f"APPROVAL_{application_id.removeprefix('APP_')}"
