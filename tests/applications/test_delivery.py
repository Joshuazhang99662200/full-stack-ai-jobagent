from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobagent.applications.approval import (
    ApplicationApprovalService,
    ApplicationDigests,
    compute_digests,
)
from jobagent.applications.audit import ApplicationAuditor
from jobagent.applications.delivery import (
    INTERVENTION_SIGNALS,
    DeliveryGate,
    intervention_required,
)
from jobagent.errors import (
    ApprovalRequiredError,
    ContractValidationError,
    StaleApprovalError,
    UnverifiedResumeVariantError,
    UserInterventionRequiredError,
)
from jobagent.schemas.applications import (
    ApplicationPackage,
    ApprovalRecord,
    DeliveryPolicy,
    DeliveryRequest,
    DeliveryResult,
    InterventionReason,
    SendResultStatus,
)

from .conftest import (
    FIXED_NOW,
    InMemoryAuditRepository,
    PackageFactory,
    RecordingDeliverySource,
    VariantFactory,
    build_variant,
)

POLICY = DeliveryPolicy()


def approval_for(package: ApplicationPackage) -> ApprovalRecord:
    return ApplicationApprovalService().approve(
        package,
        POLICY,
        confirmed=True,
        approved_at=datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
    )


def request_for(
    package: ApplicationPackage,
    approval: ApprovalRecord | None = None,
    digests: ApplicationDigests | None = None,
) -> DeliveryRequest:
    current = digests if digests is not None else compute_digests(package, POLICY)
    return DeliveryRequest(
        application_id=package.application_id,
        approval=approval if approval is not None else approval_for(package),
        job_digest=current.job_digest,
        resume_digest=current.resume_digest,
        message_digest=current.message_digest,
        policy_digest=current.policy_digest,
    )


def gate(
    source: RecordingDeliverySource,
    repository: InMemoryAuditRepository,
) -> DeliveryGate:
    return DeliveryGate(
        source=source,
        auditor=ApplicationAuditor(repository, clock=lambda: FIXED_NOW),
        policy=POLICY,
        clock=lambda: FIXED_NOW,
    )


def test_approved_and_current_application_is_delivered_once(
    package: ApplicationPackage,
    delivery_source: RecordingDeliverySource,
    audit_repository: InMemoryAuditRepository,
) -> None:
    result = gate(delivery_source, audit_repository).send(request_for(package), package)

    assert result.status is SendResultStatus.SENT
    assert delivery_source.calls == ["APP_ALPHA_001"]
    assert [audit.result for audit in audit_repository.audits] == [SendResultStatus.SENT]
    assert audit_repository.audits[0].attempt == 1
    assert audit_repository.audits[0].approval_id == "APPROVAL_ALPHA_001"


def test_send_refuses_when_the_resume_changed_after_approval(
    package_factory: PackageFactory,
    variant_factory: VariantFactory,
    delivery_source: RecordingDeliverySource,
    audit_repository: InMemoryAuditRepository,
) -> None:
    approval = approval_for(package_factory())
    edited = package_factory(variant=variant_factory(text="Led a team of forty engineers."))

    with pytest.raises(StaleApprovalError):
        gate(delivery_source, audit_repository).send(request_for(edited, approval), edited)

    assert delivery_source.calls == []
    assert [audit.result for audit in audit_repository.audits] == [SendResultStatus.FAILED]
    assert audit_repository.audits[0].failure_reason == "STALE_APPROVAL"


def test_send_refuses_a_request_whose_declared_digests_drifted(
    package: ApplicationPackage,
    delivery_source: RecordingDeliverySource,
    audit_repository: InMemoryAuditRepository,
) -> None:
    current = compute_digests(package, POLICY)
    forged = ApplicationDigests(
        application_id=current.application_id,
        job_digest=current.job_digest,
        resume_digest="sha256:stale-resume",
        message_digest=current.message_digest,
        policy_digest=current.policy_digest,
    )

    with pytest.raises(StaleApprovalError):
        gate(delivery_source, audit_repository).send(
            request_for(package, digests=forged), package
        )

    assert delivery_source.calls == []
    assert audit_repository.audits


def test_send_refuses_an_approval_minted_for_another_application(
    package_factory: PackageFactory,
    delivery_source: RecordingDeliverySource,
    audit_repository: InMemoryAuditRepository,
) -> None:
    target = package_factory(application_id="APP_ALPHA_001")
    foreign = approval_for(package_factory(application_id="APP_BETA_002"))
    request = DeliveryRequest(
        application_id=target.application_id,
        approval=foreign,
        **compute_digests(target, POLICY).as_dict(),
    )

    with pytest.raises(ApprovalRequiredError):
        gate(delivery_source, audit_repository).send(request, target)

    assert delivery_source.calls == []
    assert audit_repository.audits[0].failure_reason == "APPROVAL_REQUIRED"


def test_delivery_request_cannot_be_built_without_an_approval() -> None:
    with pytest.raises(ValidationError, match="approval"):
        DeliveryRequest(  # type: ignore[call-arg]
            application_id="APP_ALPHA_001",
            job_digest="sha256:job",
            resume_digest="sha256:resume",
            message_digest="sha256:message",
            policy_digest="sha256:policy",
        )


def test_send_refuses_a_package_whose_variant_never_passed_verification(
    package_factory: PackageFactory,
    delivery_source: RecordingDeliverySource,
    audit_repository: InMemoryAuditRepository,
) -> None:
    package = package_factory()
    tampered = package.model_copy(update={"resume_variant": build_variant(passed=False)})
    request = request_for(tampered, approval_for(package))

    with pytest.raises(UnverifiedResumeVariantError):
        gate(delivery_source, audit_repository).send(request, tampered)

    assert delivery_source.calls == []
    assert audit_repository.audits[0].failure_reason == "UNVERIFIED_RESUME_VARIANT"


def test_send_refuses_a_request_for_a_different_package(
    package_factory: PackageFactory,
    delivery_source: RecordingDeliverySource,
    audit_repository: InMemoryAuditRepository,
) -> None:
    package = package_factory(application_id="APP_ALPHA_001")
    other = package_factory(application_id="APP_BETA_002")

    with pytest.raises(ContractValidationError):
        gate(delivery_source, audit_repository).send(request_for(other), package)

    assert delivery_source.calls == []


@pytest.mark.parametrize("signal", sorted(INTERVENTION_SIGNALS))
def test_connector_intervention_is_never_retried(
    signal: str,
    package: ApplicationPackage,
    audit_repository: InMemoryAuditRepository,
) -> None:
    source = RecordingDeliverySource(
        error=intervention_required(signal, application_id=package.application_id)
    )

    with pytest.raises(UserInterventionRequiredError) as caught:
        gate(source, audit_repository).send(request_for(package), package)

    assert source.calls == ["APP_ALPHA_001"]
    assert caught.value.details["retryable"] is False
    audit = audit_repository.audits[0]
    assert audit.result is SendResultStatus.USER_INTERVENTION_REQUIRED
    assert audit.intervention_reason is INTERVENTION_SIGNALS[signal]


def test_rate_limiting_is_treated_as_risk_control_not_as_a_transient_failure() -> None:
    assert INTERVENTION_SIGNALS["rate_limit"] is InterventionReason.RISK_CONTROL
    assert INTERVENTION_SIGNALS["captcha"] is InterventionReason.CAPTCHA_REQUIRED
    assert INTERVENTION_SIGNALS["login"] is InterventionReason.LOGIN_REQUIRED


def test_intervention_reported_as_a_result_is_raised_and_audited(
    package: ApplicationPackage,
    audit_repository: InMemoryAuditRepository,
) -> None:
    source = RecordingDeliverySource(
        result=DeliveryResult(
            application_id=package.application_id,
            status=SendResultStatus.USER_INTERVENTION_REQUIRED,
            attempted_at=FIXED_NOW,
            intervention_reason=InterventionReason.CAPTCHA_REQUIRED,
        )
    )

    with pytest.raises(UserInterventionRequiredError):
        gate(source, audit_repository).send(request_for(package), package)

    assert source.calls == ["APP_ALPHA_001"]
    assert audit_repository.audits[0].intervention_reason is InterventionReason.CAPTCHA_REQUIRED


def test_a_second_send_after_intervention_must_be_a_new_explicit_call(
    package: ApplicationPackage,
    audit_repository: InMemoryAuditRepository,
) -> None:
    source = RecordingDeliverySource(
        error=intervention_required("captcha", application_id=package.application_id)
    )
    delivery_gate = gate(source, audit_repository)

    for _ in range(2):
        with pytest.raises(UserInterventionRequiredError):
            delivery_gate.send(request_for(package), package)

    assert source.calls == ["APP_ALPHA_001", "APP_ALPHA_001"]
    assert [audit.attempt for audit in audit_repository.audits] == [1, 2]


def test_connector_failure_is_audited_and_surfaced(
    package: ApplicationPackage,
    audit_repository: InMemoryAuditRepository,
) -> None:
    source = RecordingDeliverySource(
        result=DeliveryResult(
            application_id=package.application_id,
            status=SendResultStatus.FAILED,
            attempted_at=FIXED_NOW,
            failure_reason="form_rejected",
        )
    )

    result = gate(source, audit_repository).send(request_for(package), package)

    assert result.status is SendResultStatus.FAILED
    assert audit_repository.audits[0].failure_reason == "form_rejected"


def test_unexpected_connector_error_is_audited_before_it_propagates(
    package: ApplicationPackage,
    audit_repository: InMemoryAuditRepository,
) -> None:
    source = RecordingDeliverySource(error=ContractValidationError("Connector output is invalid."))

    with pytest.raises(ContractValidationError):
        gate(source, audit_repository).send(request_for(package), package)

    assert [audit.result for audit in audit_repository.audits] == [SendResultStatus.FAILED]
    assert audit_repository.audits[0].failure_reason == "CONTRACT_VALIDATION_ERROR"


def test_connector_result_for_another_application_is_rejected(
    package: ApplicationPackage,
    audit_repository: InMemoryAuditRepository,
) -> None:
    source = RecordingDeliverySource(
        result=DeliveryResult(
            application_id="APP_BETA_002",
            status=SendResultStatus.SENT,
            attempted_at=FIXED_NOW,
        )
    )

    with pytest.raises(ContractValidationError):
        gate(source, audit_repository).send(request_for(package), package)
