import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.core import TyperGroup
from typer.testing import CliRunner

from jobagent.applications.approval import ApplicationApprovalService
from jobagent.cli import applications as applications_cli
from jobagent.cli.app import app
from jobagent.errors import UserInterventionRequiredError
from jobagent.schemas.applications import (
    ApplicationPackage,
    DeliveryPolicy,
    DeliveryResult,
    InterventionReason,
    SendResultStatus,
)
from jobagent.schemas.common import ProvenanceRecord
from jobagent.schemas.jobs import MatchDecision, MatchResult, NormalizedJob
from jobagent.schemas.optimizer import (
    ClaimLedger,
    ClaimRecord,
    KeywordCoverageReport,
    OptimizedResumeItem,
    ResumeDiff,
    ResumeVariant,
    VerificationReport,
    VerificationStatus,
)

runner = CliRunner()
MESSAGE = "Hello, I would like to apply for the Python Engineer role."


def invoke(*args: str) -> tuple[int, Any]:
    result = runner.invoke(app, list(args))
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result.exit_code, payload


def job() -> NormalizedJob:
    return NormalizedJob(
        id="JOB_ALPHA_001",
        source="mock-alpha",
        source_job_id="alpha-001",
        title="Python Engineer",
        company="Example Labs",
        location="Copenhagen",
        jd_raw="Build Python API services.",
        url="https://jobs.example.test/alpha-001",
        collected_at=datetime(2026, 8, 21, tzinfo=UTC),
        provenance=[
            ProvenanceRecord(
                source="mock-alpha",
                source_id="alpha-001",
                url="https://jobs.example.test/alpha-001",
                collected_at=datetime(2026, 8, 21, tzinfo=UTC),
            )
        ],
    )


def variant(*, passed: bool = True) -> ResumeVariant:
    text = "Delivered a typed Python API used by three internal teams."
    return ResumeVariant(
        id="RESUME_ALPHA_V1",
        target_job_id="JOB_ALPHA_001",
        target_role="Python Engineer",
        selected_evidence_ids=["EVID_001"],
        items=[
            OptimizedResumeItem(
                id="ITEM_001", section="experience", text=text, evidence_ids=["EVID_001"]
            )
        ],
        claim_ledger=ClaimLedger(
            claims=[
                ClaimRecord(
                    claim_id="CLAIM_001",
                    resume_item_id="ITEM_001",
                    text=text,
                    claim_type="delivery",
                    evidence_ids=["EVID_001"],
                    verification_status=(
                        VerificationStatus.SUPPORTED if passed else VerificationStatus.UNSUPPORTED
                    ),
                )
            ]
        ),
        keyword_coverage=KeywordCoverageReport(supported_exact=["python"]),
        verification=(
            VerificationReport(passed=True, evidence_coverage=1.0)
            if passed
            else VerificationReport(passed=False, unsupported_claims=1, evidence_coverage=0.4)
        ),
        diff=ResumeDiff(),
        prompt_bundle_digest="sha256:prompt-bundle",
        generated_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def match() -> MatchResult:
    return MatchResult(
        overall=0.82,
        decision=MatchDecision.STRONG_MATCH,
        strengths=["Ships typed Python services"],
        evidence_ids=["EVID_001"],
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "job.json").write_text(job().model_dump_json(), encoding="utf-8")
    (tmp_path / "match.json").write_text(match().model_dump_json(), encoding="utf-8")
    (tmp_path / "variant.json").write_text(variant().model_dump_json(), encoding="utf-8")
    (tmp_path / "unverified.json").write_text(
        variant(passed=False).model_dump_json(), encoding="utf-8"
    )
    (tmp_path / "message.txt").write_text(MESSAGE, encoding="utf-8")
    return tmp_path


class StubDeliverySource:
    def __init__(self, outcome: DeliveryResult | Exception) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def submit_application(self, package: ApplicationPackage) -> DeliveryResult:
        self.calls.append(package.application_id)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class ConnectorHarness:
    """Install a single-application test double in place of the absent connector."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.installed: list[StubDeliverySource] = []

    def __call__(self, outcome: DeliveryResult | Exception) -> StubDeliverySource:
        source = StubDeliverySource(outcome)
        self.installed.append(source)
        self.monkeypatch.setattr(
            applications_cli, "_connector_provider", lambda platform: source
        )
        return source


@pytest.fixture
def connector(monkeypatch: pytest.MonkeyPatch) -> ConnectorHarness:
    return ConnectorHarness(monkeypatch)


def preview(workspace: Path, variant_name: str = "variant.json") -> tuple[int, Any]:
    return invoke(
        "applications",
        "preview",
        "APP_ALPHA_001",
        str(workspace / "job.json"),
        str(workspace / "match.json"),
        str(workspace / variant_name),
        str(workspace / "message.txt"),
    )


def approved(workspace: Path) -> Path:
    """Mint an approval through the service, because the CLI now requires a TTY.

    That is the point of the gate: an automated caller must not be able to
    approve on its own behalf through the documented command.
    """
    code, package = preview(workspace)
    assert code == 0
    package_path = workspace / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    record = ApplicationApprovalService().approve(
        ApplicationPackage.model_validate(package),
        DeliveryPolicy(),
        confirmed=True,
    )
    (workspace / "approval.json").write_text(record.model_dump_json(), encoding="utf-8")
    return package_path


def test_applications_group_exposes_exactly_the_delivery_chain() -> None:
    root = typer.main.get_command(app)
    assert isinstance(root, TyperGroup)
    group = root.commands["applications"]

    assert isinstance(group, TyperGroup)
    assert set(group.commands) == {"preview", "approve", "send", "audit-log"}
    for forbidden in ("send-all", "batch", "bulk", "auto", "retry"):
        assert runner.invoke(app, ["applications", forbidden]).exit_code == 2


def test_preview_emits_a_package_and_never_an_approval(workspace: Path) -> None:
    code, payload = preview(workspace)

    assert code == 0
    assert payload["application_id"] == "APP_ALPHA_001"
    assert "approval" not in payload
    assert payload["resume_variant"]["verification"]["passed"] is True


def test_preview_refuses_an_unverified_variant(workspace: Path) -> None:
    code, payload = preview(workspace, "unverified.json")

    assert code == 1
    assert payload["error"]["code"] == "UNVERIFIED_RESUME_VARIANT"
    assert MESSAGE not in json.dumps(payload)


def test_approve_requires_an_explicit_confirmation(workspace: Path) -> None:
    code, package = preview(workspace)
    package_path = workspace / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    code, payload = invoke("applications", "approve", str(package_path))

    assert code == 1
    assert payload["error"]["code"] == "APPROVAL_REQUIRED"


def test_approve_refuses_without_an_interactive_terminal(workspace: Path) -> None:
    """An agent driving the CLI has no TTY, so it cannot approve for itself."""
    code, package = preview(workspace)
    assert code == 0
    package_path = workspace / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    code, payload = invoke("applications", "approve", str(package_path), "--confirm")

    assert code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "APPROVAL_REQUIRED"
    assert "interactive terminal" in payload["error"]["message"]


def test_approve_mints_a_digest_bound_record(workspace: Path) -> None:
    approved(workspace)
    payload = json.loads((workspace / "approval.json").read_text(encoding="utf-8"))

    assert payload["approved_by"] == "human"
    assert payload["approval_id"] == "APPROVAL_ALPHA_001"
    for lane in ("job_digest", "resume_digest", "message_digest", "policy_digest"):
        assert payload[lane].startswith("sha256:")


def test_send_delivers_one_approved_application_and_writes_an_audit(
    workspace: Path,
    connector: ConnectorHarness,
) -> None:
    package_path = approved(workspace)
    connector(
        DeliveryResult(
            application_id="APP_ALPHA_001",
            status=SendResultStatus.SENT,
            attempted_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
            external_reference="EXT-1",
        )
    )
    database = workspace / "jobagent.sqlite3"

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--database",
        str(database),
    )

    assert code == 0
    assert payload["status"] == "sent"
    assert connector.installed[0].calls == ["APP_ALPHA_001"]

    code, log = invoke("applications", "audit-log", "--database", str(database))
    assert code == 0
    assert [entry["result"] for entry in log] == ["sent"]
    assert MESSAGE not in json.dumps(log)


def test_send_without_a_matching_approval_fails_loudly_and_is_audited(
    workspace: Path,
    connector: ConnectorHarness,
) -> None:
    package_path = approved(workspace)
    connector(
        DeliveryResult(
            application_id="APP_ALPHA_001",
            status=SendResultStatus.SENT,
            attempted_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        )
    )
    tampered = json.loads(package_path.read_text(encoding="utf-8"))
    tampered["message"] = "An entirely different pitch written after approval."
    package_path.write_text(json.dumps(tampered), encoding="utf-8")
    database = workspace / "jobagent.sqlite3"

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--database",
        str(database),
    )

    assert code == 1
    assert payload["error"]["code"] == "STALE_APPROVAL"
    assert connector.installed[0].calls == []

    code, log = invoke("applications", "audit-log", "--database", str(database))
    assert [entry["failure_reason"] for entry in log] == ["STALE_APPROVAL"]


def test_send_translates_captcha_into_intervention_without_retrying(
    workspace: Path,
    connector: ConnectorHarness,
) -> None:
    package_path = approved(workspace)
    connector(
        UserInterventionRequiredError(
            "CAPTCHA challenge is on screen.",
            details={"intervention_reason": InterventionReason.CAPTCHA_REQUIRED.value},
        )
    )
    database = workspace / "jobagent.sqlite3"

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--database",
        str(database),
    )

    assert code == 1
    assert payload["error"]["code"] == "USER_INTERVENTION_REQUIRED"
    assert payload["error"]["details"]["retryable"] is False
    assert connector.installed[0].calls == ["APP_ALPHA_001"]

    code, log = invoke("applications", "audit-log", "--database", str(database))
    assert [entry["result"] for entry in log] == ["user_intervention_required"]
    assert [entry["intervention_reason"] for entry in log] == ["captcha_required"]


def test_send_stops_when_no_delivery_connector_is_installed(workspace: Path) -> None:
    package_path = approved(workspace)
    database = workspace / "jobagent.sqlite3"

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--database",
        str(database),
    )

    assert code == 1
    assert payload["error"]["code"] == "USER_INTERVENTION_REQUIRED"
    assert payload["error"]["details"]["platform"] == "mock-alpha"

    code, log = invoke("applications", "audit-log", "--database", str(database))
    assert log == []


def test_send_rejects_a_malformed_approval_file(workspace: Path) -> None:
    package_path = approved(workspace)
    (workspace / "broken.json").write_text("{}", encoding="utf-8")

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "broken.json"),
        "--database",
        str(workspace / "jobagent.sqlite3"),
    )

    assert code == 1
    assert payload["error"]["code"] == "CONTRACT_VALIDATION_ERROR"


def test_audit_log_can_be_scoped_to_one_application(
    workspace: Path,
    connector: ConnectorHarness,
) -> None:
    package_path = approved(workspace)
    connector(
        DeliveryResult(
            application_id="APP_ALPHA_001",
            status=SendResultStatus.SENT,
            attempted_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        )
    )
    database = workspace / "jobagent.sqlite3"
    invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--database",
        str(database),
    )

    code, log = invoke(
        "applications",
        "audit-log",
        "--database",
        str(database),
        "--application-id",
        "APP_BETA_002",
    )

    assert code == 0
    assert log == []


def test_dry_run_reports_the_send_without_contacting_the_platform(
    workspace: Path, connector: ConnectorHarness
) -> None:
    """A rehearsal must be able to reach a recruiter under no circumstances."""
    package_path = approved(workspace)
    stub = connector(
        DeliveryResult(
            application_id="APP_ALPHA_001",
            status=SendResultStatus.SENT,
            attempted_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        )
    )

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--dry-run",
        "--database",
        str(workspace / "db.sqlite3"),
    )

    assert code == 0
    assert isinstance(payload, dict)
    assert payload["dry_run"]["would_send"] is True
    assert payload["dry_run"]["application_id"]
    assert stub.calls == [], "a dry run must not reach the connector"


def test_dry_run_writes_no_audit_record(
    workspace: Path, connector: ConnectorHarness
) -> None:
    """An attempt that never happened must not appear in the log."""
    package_path = approved(workspace)
    connector(
        DeliveryResult(
            application_id="APP_ALPHA_001",
            status=SendResultStatus.SENT,
            attempted_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        )
    )
    database = workspace / "db.sqlite3"

    invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--dry-run",
        "--database",
        str(database),
    )
    code, payload = invoke("applications", "audit-log", "--database", str(database))

    assert code == 0
    assert payload == []


def test_dry_run_still_refuses_a_stale_approval(
    workspace: Path, connector: ConnectorHarness
) -> None:
    """A rehearsal that skipped the gates would report a green result falsely."""
    package_path = approved(workspace)
    connector(
        DeliveryResult(
            application_id="APP_ALPHA_001",
            status=SendResultStatus.SENT,
            attempted_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        )
    )
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["message"] = "一条审批之后才改动的消息。"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    code, payload = invoke(
        "applications",
        "send",
        str(package_path),
        str(workspace / "approval.json"),
        "--dry-run",
        "--database",
        str(workspace / "db.sqlite3"),
    )

    assert code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "STALE_APPROVAL"
