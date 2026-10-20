import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.optimizer.review import draft_digest, evidence_digest
from jobagent.schemas.candidate import CandidateProfile
from jobagent.schemas.jobs import JobRequirementProfile
from jobagent.schemas.optimizer import (
    BaseResumeDocument,
    BaseResumeItem,
    ClaimReview,
    ClaimReviewSet,
    VerificationStatus,
)
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from tests.optimizer.test_review import draft
from tests.optimizer.test_verification import evidence


def test_cli_tailor_review_assemble_bound_handoff_with_spaces(tmp_path):
    runner = CliRunner()
    database_path = tmp_path / "private db.sqlite3"
    database = Database(database_path)
    database.migrate()
    repository = SqliteCandidateRepository(database)
    repository.save_profile(CandidateProfile(id="CAND_001"))
    repository.upsert_evidence("CAND_001", evidence())
    base = BaseResumeDocument(
        id="base",
        language="en",
        source_digest="sha256:original",
        items=[
            BaseResumeItem(
                id="ITEM_1",
                section="experience",
                text=evidence().statement,
                evidence_ids=["EVID_A"],
            ),
        ],
    )
    base_path = tmp_path / "base resume.json"
    base_path.write_text(base.model_dump_json(), encoding="utf-8")
    requirements_path = tmp_path / "req.json"
    requirements_path.write_text(
        JobRequirementProfile(job_id="JOB_1").model_dump_json(), encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "optimizer",
            "tailor",
            "CAND_001",
            "JOB_1",
            str(base_path),
            str(requirements_path),
            "--database",
            str(database_path),
            "--handoff-dir",
            str(tmp_path / "requests with spaces"),
        ],
    )
    assert result.exit_code == 0, result.output
    tailoring = json.loads(result.output)["handoff"]["details"]
    output = Path(tailoring["output_path"])
    document = draft()
    output.write_text(document.model_dump_json(), encoding="utf-8")
    result = runner.invoke(app, tailoring["resume_argv"][1:])
    assert result.exit_code == 0, result.output
    reviewing = json.loads(result.output)["handoff"]["details"]
    review = ClaimReviewSet(
        draft_digest=draft_digest(document),
        evidence_digest=evidence_digest([evidence()]),
        reviews=[
            ClaimReview(
                claim_id="CLAIM_1",
                status=VerificationStatus.SUPPORTED,
                reason="Explicit responsibility matches.",
            ),
        ],
    )
    Path(reviewing["output_path"]).write_text(review.model_dump_json(), encoding="utf-8")
    result = runner.invoke(app, reviewing["resume_argv"][1:])
    assert result.exit_code == 0, result.output
    variant = json.loads(result.output)
    assert variant["verification"]["passed"]
    assert variant["prompt_bundle_digest"] != base.source_digest
    document.items[0].text += " And invented growth."
    output.write_text(document.model_dump_json(), encoding="utf-8")
    assert runner.invoke(app, reviewing["resume_argv"][1:]).exit_code != 0


def test_cli_assemble_without_origin_cannot_pass(tmp_path):
    document = tmp_path / "draft.json"
    document.write_text(draft().model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["optimizer", "assemble", str(document), "CAND_001", "JOB_1", str(tmp_path / "base.json")],
    )
    assert result.exit_code != 0
