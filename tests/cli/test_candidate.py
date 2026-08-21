import json
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
    Skill,
)
from jobagent.schemas.common import SourceReference, SourceType, TimeRange

runner = CliRunner()


def make_pdf(path: Path) -> None:
    canvas = Canvas(str(path))
    canvas.drawString(72, 720, "Ada Lovelace - Python Engineer")
    canvas.save()


def invoke(*args: str) -> tuple[int, object]:
    result = runner.invoke(app, list(args))
    payload = json.loads(result.stdout) if result.stdout else None
    return result.exit_code, payload


def test_candidate_ingest_and_status_use_local_database(tmp_path: Path) -> None:
    database = tmp_path / "candidate.sqlite3"
    resume = tmp_path / "resume.pdf"
    make_pdf(resume)

    exit_code, ingested = invoke(
        "candidate",
        "ingest",
        "CAND_001",
        str(resume),
        "--database",
        str(database),
    )
    status_code, status = invoke(
        "candidate",
        "status",
        "CAND_001",
        "--database",
        str(database),
    )

    assert exit_code == 0
    assert isinstance(ingested, dict) and ingested["candidate_id"] == "CAND_001"
    assert status_code == 0
    assert isinstance(status, dict) and status["candidate_id"] == "CAND_001"


def test_draft_interview_confirmation_flow_is_explicit(tmp_path: Path) -> None:
    database = tmp_path / "candidate.sqlite3"
    draft_path = tmp_path / "draft.json"
    draft = CandidateDraft(
        candidate_id="CAND_001",
        profile=CandidateProfile(
            id="CAND_001",
            full_name="Ada Lovelace",
            experiences=[
                Experience(
                    id="EXP_001",
                    company="Analytical Engines",
                    title="Engineer",
                    time_range=TimeRange(),
                    evidence_ids=["EVID_001"],
                )
            ],
            skills=[Skill(name="Python", evidence_ids=["EVID_001"])],
        ),
        evidence=[
            EvidenceItem(
                id="EVID_001",
                type=EvidenceType.EXPERIENCE,
                statement="Built internal Python tooling.",
                skills=["Python"],
                source=SourceReference(
                    type=SourceType.RESUME,
                    reference="RESUME_001:page:1",
                ),
                confidence=Confidence.EXPLICIT,
            )
        ],
    )
    draft_path.write_text(draft.model_dump_json(), encoding="utf-8")

    import_code, _ = invoke(
        "candidate",
        "import-draft",
        str(draft_path),
        "--database",
        str(database),
    )
    question_code, question = invoke(
        "candidate",
        "question",
        "CAND_001",
        "--target-role",
        "Python Engineer",
        "--database",
        str(database),
    )
    assert isinstance(question, dict)
    answer_code, outcome = invoke(
        "candidate",
        "answer",
        "CAND_001",
        question["id"],
        "--answer",
        "I designed and implemented the internal API.",
        "--database",
        str(database),
    )
    assert isinstance(outcome, dict)
    evidence_id = outcome["draft_evidence"]["id"]
    confirm_code, confirmed = invoke(
        "candidate",
        "confirm",
        "CAND_001",
        evidence_id,
        "--database",
        str(database),
    )
    status_code, status = invoke(
        "candidate",
        "status",
        "CAND_001",
        "--target-role",
        "Python Engineer",
        "--database",
        str(database),
    )

    assert (import_code, question_code, answer_code, confirm_code, status_code) == (0, 0, 0, 0, 0)
    assert isinstance(confirmed, dict) and confirmed["user_confirmed"] is True
    assert isinstance(status, dict)
    assert status["readiness"]["confirmed_evidence_count"] == 1


def test_parse_error_does_not_echo_private_resume_body(tmp_path: Path) -> None:
    invalid_resume = tmp_path / "resume.pdf"
    invalid_resume.write_text("PRIVATE RESUME BODY", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "candidate",
            "ingest",
            "CAND_001",
            str(invalid_resume),
            "--database",
            str(tmp_path / "candidate.sqlite3"),
        ],
    )

    assert result.exit_code != 0
    assert "PRIVATE RESUME BODY" not in result.stdout
