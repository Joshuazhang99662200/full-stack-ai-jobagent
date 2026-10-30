import json

import pytest
from reportlab.pdfgen import canvas
from typer.testing import CliRunner

from jobagent.applications.approval import ApplicationApprovalService, compute_digests
from jobagent.cli.app import app
from jobagent.errors import ContractValidationError
from jobagent.harness.artifacts import bind_artifact, verify_artifact
from jobagent.schemas.applications import DeliveryPolicy
from tests.applications.conftest import build_package


def _pdf(path, text):
    document = canvas.Canvas(str(path))
    document.drawString(40, 700, text)
    document.save()


def test_attachment_content_changes_resume_digest_but_moving_same_file_does_not(tmp_path):
    package = build_package()
    baseline = compute_digests(package)
    first = tmp_path / "first.pdf"
    _pdf(first, package.resume_variant.items[0].text)
    package.artifact = bind_artifact(first, package.resume_variant)
    bound = compute_digests(package)
    assert bound.resume_digest != baseline.resume_digest
    package.artifact.path = str(tmp_path / "second.pdf")
    assert compute_digests(package).resume_digest == bound.resume_digest
    package.artifact.digest = "sha256:" + "0" * 64
    assert compute_digests(package).resume_digest != bound.resume_digest


@pytest.mark.parametrize("command", ["ask", "approve", "send"])
def test_every_cli_boundary_rechecks_the_final_bytes(tmp_path, command):
    package = build_package()
    path = tmp_path / "resume.pdf"
    _pdf(path, package.resume_variant.items[0].text)
    package.artifact = bind_artifact(path, package.resume_variant)
    approval = ApplicationApprovalService().approve(package, DeliveryPolicy(), confirmed=True)
    package_path = tmp_path / "package.json"
    package_path.write_text(package.model_dump_json(), encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(approval.model_dump_json(), encoding="utf-8")
    path.write_bytes(path.read_bytes() + b"\n% modified after review\n")
    args = ["applications", command, str(package_path)]
    if command == "send":
        args += [str(approval_path), "--dry-run"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert "artifact changed" in json.loads(result.stdout)["error"]["message"]


def test_non_mock_package_without_final_file_cannot_request_approval(tmp_path):
    package = build_package()
    package.job.source = "liepin"
    path = tmp_path / "package.json"
    path.write_text(package.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(app, ["applications", "ask", str(path)])
    assert result.exit_code == 1
    assert "artifact" in json.loads(result.stdout)["error"]["message"].casefold()


def test_changed_header_identity_is_not_covered_by_old_approval(tmp_path):
    from jobagent.schemas.harness import ResumeHeader

    package = build_package()
    path = tmp_path / "resume.pdf"
    _pdf(path, "Synthetic Candidate " + package.resume_variant.items[0].text)
    package.artifact = bind_artifact(
        path, package.resume_variant, ResumeHeader(lines=["Synthetic Candidate"])
    )
    before = compute_digests(package)
    package.artifact.header_lines = ["Another Candidate"]
    assert compute_digests(package).resume_digest != before.resume_digest
    with pytest.raises(ContractValidationError, match="failed checks"):
        verify_artifact(package.artifact, package.resume_variant)


@pytest.mark.parametrize("unsafe", ["invalid_bytes", "internal_note"])
def test_conversation_attachment_requires_checked_final_document(tmp_path, unsafe):
    from tests.cli.test_conversations import greeted
    from tests.harness.test_pdf import variant

    db, conversation_id, job_id = greeted(tmp_path)
    document = variant().model_copy(update={"target_job_id": job_id})
    path = tmp_path / "resume.pdf"
    if unsafe == "invalid_bytes":
        path.write_bytes(b"not a real PDF")
    else:
        document.items[0].text = "Internal note: drafting instructions."
        _pdf(path, document.items[0].text)
    variant_path = tmp_path / "variant.json"
    variant_path.write_text(document.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "conversations",
            "attach-resume",
            conversation_id,
            str(variant_path),
            str(path),
            *db,
        ],
    )
    assert result.exit_code == 1
    assert "artifact failed checks" in json.loads(result.stdout)["error"]["message"]
