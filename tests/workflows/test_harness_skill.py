"""Install, confirm synthetic evidence, review, render, approve a rehearsal and hand off."""

import json
import subprocess
import sys
from pathlib import Path

from jobagent.schemas.candidate import CandidateDraft, CandidateProfile
from jobagent.schemas.jobs import JobRequirementProfile
from tests.applications.conftest import build_job, build_match
from tests.harness.test_distribution import builder
from tests.harness.test_pdf import render
from tests.optimizer.test_review import draft, review
from tests.optimizer.test_verification import evidence


def test_installed_harness_workflow_without_checkout_cwd(tmp_path):
    skill = builder()(tmp_path / "installed skill/job-hunting", "codex")
    workspace = tmp_path / "personal workspace"
    private = workspace / ".jobagent/fixture"
    private.mkdir(parents=True)
    launcher = [sys.executable, str(skill / "scripts/bootstrap.py"), "--workspace", str(workspace)]

    def command(*args, expected=0):
        result = subprocess.run(
            [*launcher, "--", *map(str, args)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return json.loads(result.stdout)

    def save(name, payload):
        path = private / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    check = subprocess.run([*launcher, "--check"], capture_output=True, text=True, check=False)
    assert json.loads(check.stdout)["integrity"] == "ok"
    run = command("harness", "start", "CAND_001", "codex", "--session-id", "fixture-a")
    candidate = CandidateDraft(
        candidate_id="CAND_001",
        profile=CandidateProfile(id="CAND_001"),
        evidence=[evidence(confirmed=False)],
    )
    candidate_path = save("candidate.json", candidate.model_dump(mode="json"))
    command("candidate", "import-draft", candidate_path)
    assert command("candidate", "confirm", "CAND_001", "EVID_A")["user_confirmed"]
    base = command("optimizer", "base-resume", "CAND_001")
    base_path = save("base.json", base)
    requirements = JobRequirementProfile(job_id="JOB_1", skills=["migration"])
    requirement_path = save("requirements.json", requirements.model_dump(mode="json"))
    handoff = command("optimizer", "tailor", "CAND_001", "JOB_1", base_path, requirement_path)[
        "handoff"
    ]["details"]
    document = draft()
    Path(handoff["output_path"]).write_text(document.model_dump_json(), encoding="utf-8")
    review_handoff = command(*handoff["resume_argv"][1:])["handoff"]["details"]
    Path(review_handoff["output_path"]).write_text(
        review(document).model_dump_json(), encoding="utf-8"
    )
    variant = command(*review_handoff["resume_argv"][1:])
    assert variant["verification"]["passed"]
    variant_path = save("variant.json", variant)
    pdf_path = private / "resume.pdf"
    render(pdf_path, document.items[0].text)
    assert command("harness", "check-pdf", variant_path, pdf_path)["passed"]
    job = build_job("JOB_1", title="Platform Engineer")
    job.source = "liepin"
    job.job_kind = "2"
    job.jd_raw = "Lead a platform migration."
    job_path = save("job.json", job.model_dump(mode="json"))
    match_path = save("match.json", build_match().model_dump(mode="json"))
    message = private / "message.txt"
    message.write_text("I would like to discuss this migration role.", encoding="utf-8")
    package = command(
        "applications", "preview", "APP_FIXTURE", job_path, match_path, variant_path, message
    )
    package_path = save("package.json", package)
    command(
        "harness",
        "checkpoint",
        run["run_id"],
        "waiting_for_approval",
        "--session-id",
        "fixture-a",
        "--artifact",
        package_path,
        "--contract",
        "ApplicationPackage",
    )
    ask_path = save("ask.json", command("applications", "ask", package_path))
    # Test-only synthetic human response; no real person, account or sending is involved.
    approval = command(
        "applications",
        "approve",
        package_path,
        "--confirm",
        "--request",
        ask_path,
        "--answer",
        "Synthetic human explicitly approves this fixture package.",
    )
    approval_path = save("approval.json", approval)
    rehearsal = command("applications", "send", package_path, approval_path, "--dry-run")
    assert "dry_run" in rehearsal
    assert command("applications", "audit-log") == []
    assert command("harness", "report", run["run_id"])["outcomes"][0]["status"] == "unknown"
    intervention = command("applications", "send", package_path, approval_path, expected=1)
    assert intervention["error"]["code"] == "USER_INTERVENTION_REQUIRED"
    assert (
        command("harness", "report", run["run_id"])["outcomes"][0]["status"]
        == "user_intervention_required"
    )
    command("harness", "release", run["run_id"], "--session-id", "fixture-a")
    assert (
        command("harness", "resume", run["run_id"], "claude-code", "--session-id", "fixture-b")[
            "run_id"
        ]
        == run["run_id"]
    )
