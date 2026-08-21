import pytest
from pydantic import ValidationError

from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    InterviewAnswer,
    InterviewQuestion,
    ParsedResume,
    ResumePage,
    Skill,
)
from jobagent.schemas.common import SourceReference, SourceType


def test_evidence_requires_statement_and_source() -> None:
    item = EvidenceItem(
        id="EVID_001",
        type=EvidenceType.ACHIEVEMENT,
        statement="Reduced review time by 30%.",
        source=SourceReference(type=SourceType.RESUME, reference="page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=True,
    )
    assert item.id == "EVID_001"


def test_confirmed_evidence_cannot_be_weak() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            id="EVID_002",
            type=EvidenceType.SKILL,
            statement="May know RAG.",
            source=SourceReference(type=SourceType.RESUME, reference="page:2"),
            confidence=Confidence.WEAK,
            user_confirmed=True,
        )


def test_resume_page_numbers_start_at_one() -> None:
    with pytest.raises(ValidationError):
        ResumePage(page_number=0, text="Resume text")


def test_parsed_resume_requires_digest_and_at_least_one_page() -> None:
    resume = ParsedResume(
        id="RESUME_001",
        candidate_id="CAND_001",
        source_name="resume.pdf",
        content_digest="sha256:abc123",
        pages=[ResumePage(page_number=1, text="Candidate experience")],
    )
    assert resume.pages[0].page_number == 1

    with pytest.raises(ValidationError):
        ParsedResume(
            id="RESUME_002",
            candidate_id="CAND_001",
            source_name="resume.pdf",
            content_digest="invalid",
            pages=[],
        )


def test_candidate_draft_references_only_its_profile_evidence() -> None:
    evidence = EvidenceItem(
        id="EVID_001",
        type=EvidenceType.EXPERIENCE,
        statement="Built internal tooling.",
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=Confidence.EXPLICIT,
    )
    draft = CandidateDraft(
        candidate_id="CAND_001",
        profile=CandidateProfile(id="CAND_001"),
        evidence=[evidence],
    )
    assert draft.candidate_id == draft.profile.id

    with pytest.raises(ValidationError):
        CandidateDraft(
            candidate_id="CAND_002",
            profile=CandidateProfile(id="CAND_001"),
            evidence=[evidence],
        )

    with pytest.raises(ValidationError):
        CandidateDraft(
            candidate_id="CAND_001",
            profile=CandidateProfile(
                id="CAND_001",
                skills=[Skill(name="Python", evidence_ids=["EVID_MISSING"])],
            ),
            evidence=[evidence],
        )


def test_interview_question_has_one_primary_gap() -> None:
    question = InterviewQuestion(
        id="QUESTION_001",
        candidate_id="CAND_001",
        primary_gap_id="GAP_001",
        text="What was your scope on the project?",
        reason="Ownership is ambiguous.",
        expected_information="Individual contribution and decision authority",
        score=0.9,
    )
    assert question.primary_gap_id == "GAP_001"


def test_interview_answer_is_either_answered_or_skipped() -> None:
    answered = InterviewAnswer(question_id="QUESTION_001", answer="I owned the API design.")
    skipped = InterviewAnswer(question_id="QUESTION_002", skipped=True)
    assert answered.answer is not None
    assert skipped.answer is None

    with pytest.raises(ValidationError):
        InterviewAnswer(question_id="QUESTION_003")

    with pytest.raises(ValidationError):
        InterviewAnswer(question_id="QUESTION_004", answer="Some answer", skipped=True)
