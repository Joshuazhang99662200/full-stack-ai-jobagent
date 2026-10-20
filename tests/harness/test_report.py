from jobagent.harness.reporting import build_report
from jobagent.schemas.applications import ApplicationAudit, SendResultStatus
from tests.applications.conftest import FIXED_NOW, build_package


def audit(package, result=SendResultStatus.SENT, attempt=1):
    return ApplicationAudit(
        audit_id=f"AUDIT_TEST_{attempt}",
        application_id=package.application_id,
        job_id=package.job.id,
        platform=package.job.source,
        resume_variant_id=package.resume_variant.id,
        resume_digest="sha256:r",
        message_digest="sha256:m",
        attempt=attempt,
        result=result,
        timestamp=FIXED_NOW,
    )


def test_report_never_infers_delivery_from_generated_package():
    package = build_package()
    report = build_report("RUN_" + "A" * 32, [package], [])
    assert report.outcomes[0].status == "unknown"


def test_report_uses_last_actual_audit_and_marks_simulation():
    package = build_package()
    assert (
        build_report("RUN_" + "A" * 32, [package], [audit(package)]).outcomes[0].status
        == "simulated"
    )
    package.job.source = "liepin"
    report = build_report(
        "RUN_" + "A" * 32,
        [package],
        [audit(package), audit(package, SendResultStatus.USER_INTERVENTION_REQUIRED, 2)],
    )
    assert report.outcomes[0].status == "user_intervention_required"
    assert report.outcomes[0].attempts == 2
    assert "message" not in report.outcomes[0].model_dump()
