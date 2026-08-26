"""Delivery performs an authorized send. It never decides to send."""

import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from jobagent.applications.ports import ApplicationDeliverySource
from jobagent.connectors.liepin_delivery import LiepinCliDeliverySource
from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.applications import ApplicationPackage, InterventionReason, SendResultStatus
from jobagent.schemas.common import ProvenanceRecord
from jobagent.schemas.jobs import MatchDecision, MatchResult, NormalizedJob
from jobagent.schemas.optimizer import (
    ClaimLedger,
    KeywordCoverageReport,
    ResumeDiff,
    ResumeVariant,
    VerificationReport,
)


def job(*, source: str = "liepin", job_kind: str | None = "2") -> NormalizedJob:
    return NormalizedJob(
        id="JOB_TEST1",
        source=source,
        source_job_id="1976319881",
        title="大模型产品经理",
        company="宁波银行",
        location="上海",
        jd_raw="负责大模型产品设计工作。",
        url="https://www.liepin.com/job/1976319881.shtml",
        job_kind=job_kind,
        collected_at=datetime.now(UTC),
        provenance=[
            ProvenanceRecord(
                source="liepin", source_id="1976319881", collected_at=datetime.now(UTC)
            )
        ],
    )


def package(**kwargs: object) -> ApplicationPackage:
    variant = ResumeVariant(
        id="RESUME_V1",
        target_job_id="JOB_TEST1",
        target_role="大模型产品经理",
        claim_ledger=ClaimLedger(),
        keyword_coverage=KeywordCoverageReport(),
        verification=VerificationReport(passed=True, evidence_coverage=1.0),
        diff=ResumeDiff(),
        prompt_bundle_digest="sha256:" + "c" * 64,
        generated_at=datetime.now(UTC),
    )
    return ApplicationPackage(
        application_id="APP_1",
        job=job(**kwargs),  # type: ignore[arg-type]
        match=MatchResult(overall=0.7, decision=MatchDecision.POSSIBLE_MATCH, strengths=["契合"]),
        resume_variant=variant,
        message="您好,我对该职位很感兴趣。",
        prepared_at=datetime.now(UTC),
    )


def runner_for(*, stdout: bytes = b"{}", stderr: bytes = b"", returncode: int = 0, record=None):
    def run(command: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
        if record is not None:
            record.append(list(command))
        return subprocess.CompletedProcess(list(command), returncode, stdout, stderr)

    return run


def test_source_satisfies_the_delivery_port() -> None:
    assert isinstance(LiepinCliDeliverySource(runner=runner_for()), ApplicationDeliverySource)


def test_no_plural_delivery_operation_exists() -> None:
    """The port has no batch call, and neither may an implementation."""
    source = LiepinCliDeliverySource(runner=runner_for())
    for forbidden in ("submit_applications", "submit_all", "submit_batch", "send_all"):
        assert not hasattr(source, forbidden)


def test_successful_submit_echoes_the_platform_job_kind() -> None:
    commands: list[Sequence[str]] = []
    source = LiepinCliDeliverySource(
        runner=runner_for(stdout=b'{"applyId": "A-993"}', record=commands)
    )

    result = source.submit_application(package())

    assert result.status is SendResultStatus.SENT
    assert result.external_reference == "A-993"
    assert commands == [
        [
            "liepin-cli",
            "job",
            "apply",
            "--job-id",
            "1976319881",
            "--job-kind",
            "2",
            "--output",
            "json",
        ]
    ]


def test_missing_job_kind_refuses_rather_than_guessing() -> None:
    """Upstream forbids inventing the kind; a wrong kind applies to the wrong posting."""
    source = LiepinCliDeliverySource(runner=runner_for())

    with pytest.raises(ContractValidationError, match="must not be guessed"):
        source.submit_application(package(job_kind=None))


def test_unrecognised_job_kind_is_refused() -> None:
    source = LiepinCliDeliverySource(runner=runner_for())
    with pytest.raises(ContractValidationError, match="not one the platform accepts"):
        source.submit_application(package(job_kind="9"))


def test_a_package_from_another_source_is_refused() -> None:
    source = LiepinCliDeliverySource(runner=runner_for())
    with pytest.raises(ContractValidationError, match="only handles Liepin"):
        source.submit_application(package(source="zhaopin"))


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        (b"\xe8\xaf\xb7\xe5\x85\x88\xe7\x99\xbb\xe5\xbd\x95", InterventionReason.LOGIN_REQUIRED),
        (b"HTTP 401 unauthorized", InterventionReason.LOGIN_REQUIRED),
        (b"x-user-token expired", InterventionReason.LOGIN_REQUIRED),
        (b"captcha required", InterventionReason.CAPTCHA_REQUIRED),
        (b"HTTP 429 too many requests", InterventionReason.RISK_CONTROL),
        (b"HTTP 403 forbidden", InterventionReason.RISK_CONTROL),
    ],
)
def test_platform_states_hand_control_back_and_are_never_retried(
    stderr: bytes, reason: InterventionReason
) -> None:
    commands: list[Sequence[str]] = []
    source = LiepinCliDeliverySource(
        runner=runner_for(returncode=1, stderr=stderr, record=commands)
    )

    result = source.submit_application(package())

    assert result.status is SendResultStatus.USER_INTERVENTION_REQUIRED
    assert result.intervention_reason is reason
    assert len(commands) == 1, "an intervention must never be retried"


def test_rate_limiting_is_risk_control_not_a_transient_fault() -> None:
    """Slowing down to probe a limit is itself a workaround; stop instead."""
    source = LiepinCliDeliverySource(runner=runner_for(returncode=1, stderr=b"429"))
    result = source.submit_application(package())
    assert result.intervention_reason is InterventionReason.RISK_CONTROL


def test_silent_exit_two_is_treated_as_needing_authorization() -> None:
    source = LiepinCliDeliverySource(runner=runner_for(returncode=2, stderr=b""))

    result = source.submit_application(package())

    assert result.status is SendResultStatus.USER_INTERVENTION_REQUIRED
    assert "liepin-cli setup" in (result.failure_reason or "")


def test_other_failures_are_failed_not_disguised_as_intervention() -> None:
    source = LiepinCliDeliverySource(runner=runner_for(returncode=1, stderr=b"internal error"))
    result = source.submit_application(package())
    assert result.status is SendResultStatus.FAILED
    assert result.intervention_reason is None


def test_timeout_asks_a_person_to_check_before_any_resend() -> None:
    """A timed-out submit may already have landed; resending would double-apply."""

    def run(command: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
        raise subprocess.TimeoutExpired(list(command), 120)

    result = LiepinCliDeliverySource(runner=run).submit_application(package())

    assert result.status is SendResultStatus.USER_INTERVENTION_REQUIRED
    assert "whether the application was submitted" in (result.failure_reason or "")


def test_missing_executable_is_user_intervention() -> None:
    def run(command: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
        raise FileNotFoundError(command[0])

    with pytest.raises(UserInterventionRequiredError, match="not installed"):
        LiepinCliDeliverySource(runner=run).submit_application(package())


def test_gbk_stderr_is_decoded_before_matching() -> None:
    """Upstream emits cp936 on a pipe; a mojibake message would miss the marker."""
    source = LiepinCliDeliverySource(
        runner=runner_for(returncode=1, stderr="触发风控".encode("gb18030"))
    )
    result = source.submit_application(package())
    assert result.intervention_reason is InterventionReason.RISK_CONTROL


def test_unparseable_success_output_falls_back_to_the_source_job_id() -> None:
    source = LiepinCliDeliverySource(runner=runner_for(stdout=b"ok"))
    result = source.submit_application(package())
    assert result.status is SendResultStatus.SENT
    assert result.external_reference == "1976319881"


def test_submit_never_reads_or_writes_the_online_resume() -> None:
    commands: list[Sequence[str]] = []
    LiepinCliDeliverySource(runner=runner_for(record=commands)).submit_application(package())
    flat = " ".join(commands[0])
    for forbidden in ("resume", "update", "add-", "setup"):
        assert forbidden not in flat, forbidden


def test_json_payload_is_valid_for_the_upstream_contract() -> None:
    """`jobKind` is required upstream and constrained to "1" or "2"."""
    commands: list[Sequence[str]] = []
    LiepinCliDeliverySource(runner=runner_for(record=commands)).submit_application(package())
    argv = commands[0]
    assert argv[argv.index("--job-kind") + 1] in {"1", "2"}
    assert json.dumps({"jobId": int(argv[argv.index("--job-id") + 1])})
