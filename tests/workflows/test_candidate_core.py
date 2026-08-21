from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.pdfgen.canvas import Canvas

from jobagent.candidate.evidence import CandidateEvidenceService
from jobagent.candidate.gaps import GapDetector
from jobagent.candidate.interview import AdaptiveInterview
from jobagent.candidate.onboarding import CandidateOnboardingService
from jobagent.candidate.readiness import CandidateReadinessService
from jobagent.parsing.pdf_resume import PdfResumeParser
from jobagent.reasoning.candidate_extractor import ReasoningCandidateDraftExtractor
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
    InterviewAnswer,
    Skill,
)
from jobagent.schemas.common import ContractModel, SourceReference, SourceType, TimeRange
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database


class CandidateDraftProvider:
    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ContractModel],
    ) -> Any:
        assert prompt_id == "candidate.extract_draft.v1"
        candidate_id = str(context["candidate_id"])
        resume_id = str(context["resume_id"])
        return CandidateDraft(
            candidate_id=candidate_id,
            profile=CandidateProfile(
                id=candidate_id,
                full_name="Ada Lovelace",
                experiences=[
                    Experience(
                        id="EXP_001",
                        company="Analytical Engines",
                        title="Engineer",
                        time_range=TimeRange(),
                        evidence_ids=["EVID_BASE"],
                    )
                ],
                skills=[Skill(name="Python", evidence_ids=["EVID_BASE"])],
            ),
            evidence=[
                EvidenceItem(
                    id="EVID_BASE",
                    type=EvidenceType.EXPERIENCE,
                    statement="Built internal Python tooling.",
                    skills=["Python"],
                    source=SourceReference(
                        type=SourceType.RESUME,
                        reference=f"{resume_id}:page:1",
                    ),
                    confidence=Confidence.EXPLICIT,
                )
            ],
        )


def make_resume(path: Path) -> None:
    canvas = Canvas(str(path))
    canvas.drawString(72, 720, "Ada Lovelace - Python Engineer")
    canvas.showPage()
    canvas.drawString(72, 720, "Built internal Python tooling")
    canvas.save()


def test_offline_candidate_core_workflow(tmp_path: Path) -> None:
    source_path = tmp_path / "resume.pdf"
    make_resume(source_path)
    database = Database(tmp_path / "candidate.sqlite3")
    database.migrate()
    repository = SqliteCandidateRepository(database)
    onboarding = CandidateOnboardingService(
        PdfResumeParser(),
        ReasoningCandidateDraftExtractor(CandidateDraftProvider()),
        repository,
    )

    draft = onboarding.ingest_resume(source_path, "CAND_001")
    resume_id = draft.evidence[0].source.reference.split(":", maxsplit=1)[0]
    parsed = repository.get_resume(resume_id)
    assert parsed is not None
    assert len(parsed.pages) == 2
    assert parsed.content_digest.startswith("sha256:")

    profile = repository.get_profile("CAND_001")
    assert profile is not None
    evidence = repository.list_evidence("CAND_001")
    before = CandidateReadinessService().evaluate(
        profile,
        evidence,
        target_role="Python Engineer",
    )
    gaps = GapDetector().detect(profile, evidence, target_role="Python Engineer")
    question = AdaptiveInterview().next_question(
        "CAND_001",
        gaps,
        target_role="Python Engineer",
    )
    assert question is not None

    outcome = AdaptiveInterview().record_answer(
        question,
        InterviewAnswer(
            question_id=question.id,
            answer="I owned the API design and implementation.",
        ),
        evidence_id="EVID_INTERVIEW_001",
        event_id="EVENT_ANSWER_001",
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    repository.save_interview_outcome(outcome)
    confirmed = CandidateEvidenceService(repository).confirm(
        "CAND_001",
        "EVID_INTERVIEW_001",
    )
    after = CandidateReadinessService().evaluate(
        profile,
        repository.list_evidence("CAND_001"),
        target_role="Python Engineer",
    )

    assert confirmed.user_confirmed
    assert before.readiness.confirmed_evidence_count == 0
    assert after.readiness.confirmed_evidence_count == 1
    assert after.readiness.target_role_readiness > before.readiness.target_role_readiness
