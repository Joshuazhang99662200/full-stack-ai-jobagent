from datetime import UTC, datetime

import pytest

from jobagent.applications.approval import (
    ApplicationApprovalService,
    compute_digests,
    verify_approval_is_current,
)
from jobagent.errors import (
    ApprovalRequiredError,
    StaleApprovalError,
    UnverifiedResumeVariantError,
)
from jobagent.schemas.applications import ApplicationPackage, DeliveryPolicy

from .conftest import JobFactory, PackageFactory, VariantFactory, build_variant

POLICY = DeliveryPolicy()


def approve(package: ApplicationPackage) -> object:
    return ApplicationApprovalService().approve(
        package,
        POLICY,
        confirmed=True,
        approved_at=datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
    )


def test_digests_are_stable_across_runs_for_identical_input(
    package_factory: PackageFactory,
) -> None:
    first = compute_digests(package_factory(), POLICY)
    second = compute_digests(package_factory(), POLICY)

    assert first == second
    for value in (first.job_digest, first.resume_digest, first.message_digest, first.policy_digest):
        assert value.startswith("sha256:")


def test_digests_ignore_production_timestamps_but_not_content(
    package_factory: PackageFactory,
    variant_factory: VariantFactory,
) -> None:
    baseline = compute_digests(package_factory(), POLICY)
    later = compute_digests(
        package_factory(
            prepared_at=datetime(2027, 1, 1, tzinfo=UTC),
            variant=variant_factory(generated_at=datetime(2027, 1, 1, tzinfo=UTC)),
        ),
        POLICY,
    )
    edited = compute_digests(
        package_factory(variant=variant_factory(text="Led a team of forty engineers.")),
        POLICY,
    )

    assert later.resume_digest == baseline.resume_digest
    assert edited.resume_digest != baseline.resume_digest


def test_each_artifact_has_its_own_digest_lane(package_factory: PackageFactory) -> None:
    baseline = compute_digests(package_factory(), POLICY)
    other_message = compute_digests(package_factory(message="A different pitch entirely."), POLICY)

    assert other_message.message_digest != baseline.message_digest
    assert other_message.job_digest == baseline.job_digest
    assert other_message.resume_digest == baseline.resume_digest


def test_approval_binds_a_human_to_the_exact_artifacts(package: ApplicationPackage) -> None:
    record = approve(package)
    digests = compute_digests(package, POLICY)

    assert record.approved_by == "human"
    assert record.application_id == "APP_ALPHA_001"
    assert record.approval_id == "APPROVAL_ALPHA_001"
    assert record.matches(
        job_digest=digests.job_digest,
        resume_digest=digests.resume_digest,
        message_digest=digests.message_digest,
        policy_digest=digests.policy_digest,
    )


def test_approval_requires_an_explicit_human_confirmation(package: ApplicationPackage) -> None:
    with pytest.raises(ApprovalRequiredError) as caught:
        ApplicationApprovalService().approve(package, POLICY, confirmed=False)

    assert caught.value.code == "APPROVAL_REQUIRED"


def test_approval_refuses_a_package_holding_an_unverified_variant(
    package_factory: PackageFactory,
) -> None:
    package = package_factory()
    tampered = package.model_copy(update={"resume_variant": build_variant(passed=False)})

    with pytest.raises(UnverifiedResumeVariantError):
        approve(tampered)


def test_verify_approval_is_current_accepts_unchanged_artifacts(
    package: ApplicationPackage,
) -> None:
    verify_approval_is_current(approve(package), compute_digests(package, POLICY))


@pytest.mark.parametrize("lane", ["message_digest", "resume_digest", "job_digest"])
def test_any_artifact_change_makes_the_approval_stale(
    package_factory: PackageFactory,
    variant_factory: VariantFactory,
    job_factory: JobFactory,
    lane: str,
) -> None:
    approval = approve(package_factory())
    changed = {
        "message_digest": lambda: package_factory(message="A completely rewritten pitch."),
        "resume_digest": lambda: package_factory(
            variant=variant_factory(text="Led a team of forty engineers.")
        ),
        "job_digest": lambda: package_factory(job=job_factory(title="Staff Python Engineer")),
    }[lane]()

    with pytest.raises(StaleApprovalError) as caught:
        verify_approval_is_current(approval, compute_digests(changed, POLICY))

    assert caught.value.code == "STALE_APPROVAL"
    assert caught.value.details["changed"] == [lane]


def test_policy_change_makes_the_approval_stale(package: ApplicationPackage) -> None:
    approval = approve(package)
    digests = compute_digests(package, POLICY)
    forged = type(digests)(
        application_id=digests.application_id,
        job_digest=digests.job_digest,
        resume_digest=digests.resume_digest,
        message_digest=digests.message_digest,
        policy_digest="sha256:some-other-policy",
    )

    with pytest.raises(StaleApprovalError) as caught:
        verify_approval_is_current(approval, forged)

    assert caught.value.details["changed"] == ["policy_digest"]


def test_approval_for_another_application_is_not_an_approval(
    package_factory: PackageFactory,
) -> None:
    approval = approve(package_factory(application_id="APP_ALPHA_001"))
    other = compute_digests(package_factory(application_id="APP_BETA_002"), POLICY)

    with pytest.raises(ApprovalRequiredError) as caught:
        verify_approval_is_current(approval, other)

    assert caught.value.details["application_id"] == "APP_BETA_002"


def test_stale_approval_details_never_echo_message_or_resume_text(
    package_factory: PackageFactory,
) -> None:
    secret = "A completely rewritten pitch that must stay private."
    approval = approve(package_factory())

    changed = compute_digests(package_factory(message=secret), POLICY)

    with pytest.raises(StaleApprovalError) as caught:
        verify_approval_is_current(approval, changed)

    assert secret not in repr(caught.value.details) + str(caught.value)


def test_delivery_policy_cannot_represent_a_bypass() -> None:
    assert DeliveryPolicy().max_applications_per_request == 1
    assert DeliveryPolicy().retry_on_user_intervention is False
    for field, value in (
        ("max_applications_per_request", 5),
        ("retry_on_user_intervention", True),
        ("require_matching_approval", False),
        ("require_verified_resume_variant", False),
    ):
        with pytest.raises(ValueError, match=field):
            DeliveryPolicy(**{field: value})
