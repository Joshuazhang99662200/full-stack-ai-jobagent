import pytest

from jobagent.applications.preview import ApplicationPreviewService
from jobagent.errors import ContractValidationError, UnverifiedResumeVariantError
from jobagent.schemas.applications import ApplicationPackage

from .conftest import FIXED_NOW, JobFactory, VariantFactory, build_job, build_match, build_variant


def prepare(**overrides: object) -> ApplicationPackage:
    arguments: dict[str, object] = {
        "application_id": "APP_ALPHA_001",
        "job": build_job(),
        "match": build_match(),
        "resume_variant": build_variant(),
        "message": "Hello, I would like to apply for the Python Engineer role.",
        "prepared_at": FIXED_NOW,
    }
    arguments.update(overrides)
    return ApplicationPreviewService().prepare(**arguments)  # type: ignore[arg-type]


def test_preview_assembles_a_reviewable_package_without_approving_it() -> None:
    package = prepare()

    assert package.application_id == "APP_ALPHA_001"
    assert package.job.id == "JOB_ALPHA_001"
    assert package.resume_variant.verification.passed is True
    assert package.prepared_at == FIXED_NOW
    assert not hasattr(package, "approval")
    assert not hasattr(package, "approved_at")


def test_preview_refuses_a_variant_that_failed_verification(
    variant_factory: VariantFactory,
) -> None:
    with pytest.raises(UnverifiedResumeVariantError) as caught:
        prepare(resume_variant=variant_factory(passed=False))

    assert caught.value.code == "UNVERIFIED_RESUME_VARIANT"
    assert caught.value.details["resume_variant_id"] == "RESUME_ALPHA_V1"
    assert caught.value.details["issue_codes"] == ["UNSUPPORTED_CLAIM"]


def test_refusal_details_never_echo_resume_or_message_text(
    variant_factory: VariantFactory,
) -> None:
    secret = "Delivered a typed Python API used by three internal teams."
    with pytest.raises(UnverifiedResumeVariantError) as caught:
        prepare(resume_variant=variant_factory(passed=False, text=secret))

    rendered = repr(caught.value.details) + str(caught.value)
    assert secret not in rendered
    assert "Python Engineer role" not in rendered


def test_preview_refuses_a_variant_targeting_another_job(
    job_factory: JobFactory,
    variant_factory: VariantFactory,
) -> None:
    with pytest.raises(ContractValidationError) as caught:
        prepare(job=job_factory("JOB_BETA_002"), resume_variant=variant_factory())

    assert caught.value.details["job_id"] == "JOB_BETA_002"
    assert caught.value.details["target_job_id"] == "JOB_ALPHA_001"


def test_preview_refuses_an_empty_message() -> None:
    with pytest.raises(ContractValidationError):
        prepare(message="   ")


def test_preview_refuses_a_malformed_application_id() -> None:
    with pytest.raises(ContractValidationError) as caught:
        prepare(application_id="not-an-application-id")

    assert caught.value.code == "CONTRACT_VALIDATION_ERROR"


def test_preview_is_deterministic_for_identical_input() -> None:
    assert prepare().model_dump_json() == prepare().model_dump_json()


def test_preview_carries_reviewer_risks_verbatim() -> None:
    package = prepare(risks=["Salary band undisclosed"])

    assert package.risks == ["Salary band undisclosed"]
