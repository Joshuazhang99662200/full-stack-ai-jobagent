"""Thin Candidate Core CLI commands."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Never
from uuid import uuid4

import typer
from pydantic import ValidationError

from jobagent.candidate.evidence import CandidateEvidenceService
from jobagent.candidate.gaps import GapDetector
from jobagent.candidate.interview import AdaptiveInterview
from jobagent.candidate.readiness import CandidateReadinessService
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.parsing.pdf_resume import PdfResumeParser
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    InterviewAnswer,
    InterviewEvent,
    InterviewEventType,
    InterviewQuestion,
)
from jobagent.schemas.common import ContractModel
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite database path.")]

candidate_app = typer.Typer(help="Build and review the local candidate knowledge base.")


def _repository(path: Path) -> SqliteCandidateRepository:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteCandidateRepository(database)


def _emit(value: ContractModel | None) -> None:
    typer.echo("null" if value is None else value.model_dump_json(indent=2))


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(code=1)


def _input_error(message: str) -> Never:
    _fail(ContractValidationError(message))


def _required_profile(
    repository: SqliteCandidateRepository,
    candidate_id: str,
) -> CandidateProfile:
    profile = repository.get_profile(candidate_id)
    if profile is None:
        raise ContractValidationError(
            "Candidate profile was not found.",
            details={"candidate_id": candidate_id},
        )
    return profile


@candidate_app.command("ingest")
def ingest(
    candidate_id: str,
    resume_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Parse and store a local PDF source without interpreting its claims."""
    try:
        repository = _repository(database)
        if repository.get_profile(candidate_id) is None:
            repository.save_profile(CandidateProfile(id=candidate_id))
        parsed = PdfResumeParser().parse(resume_path, candidate_id)
        repository.save_resume(parsed)
        _emit(parsed)
    except JobAgentError as error:
        _fail(error)


@candidate_app.command("import-draft")
def import_draft(
    draft_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Import a reviewed structured draft; all evidence remains unconfirmed."""
    try:
        draft = CandidateDraft.model_validate_json(draft_path.read_text(encoding="utf-8"))
        _repository(database).save_draft(draft)
        _emit(draft)
    except (OSError, ValidationError) as error:
        _input_error(f"Candidate draft could not be loaded: {type(error).__name__}.")
    except JobAgentError as error:
        _fail(error)


@candidate_app.command("question")
def question(
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    target_role: Annotated[str | None, typer.Option("--target-role")] = None,
) -> None:
    """Select and record at most one adaptive interview question."""
    try:
        repository = _repository(database)
        profile = _required_profile(repository, candidate_id)
        evidence = repository.list_evidence(candidate_id)
        gaps = GapDetector().detect(profile, evidence, target_role=target_role)
        events = repository.list_interview_events(candidate_id)
        recent_gap_ids = {
            str(event.payload["question"]["primary_gap_id"])
            for event in events[-5:]
            if event.event_type is InterviewEventType.QUESTION
            and isinstance(event.payload.get("question"), dict)
            and "primary_gap_id" in event.payload["question"]
        }
        selected = AdaptiveInterview().next_question(
            candidate_id,
            gaps,
            target_role=target_role,
            recent_gap_ids=recent_gap_ids,
        )
        if selected is not None:
            repository.append_interview_event(
                InterviewEvent(
                    id=f"EVENT_{uuid4().hex.upper()}",
                    candidate_id=candidate_id,
                    event_type=InterviewEventType.QUESTION,
                    question_id=selected.id,
                    payload={"question": selected.model_dump(mode="json")},
                    created_at=datetime.now(UTC),
                )
            )
        _emit(selected)
    except JobAgentError as error:
        _fail(error)


@candidate_app.command("answer")
def answer(
    candidate_id: str,
    question_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    answer_text: Annotated[str | None, typer.Option("--answer")] = None,
    skip: Annotated[bool, typer.Option("--skip")] = False,
) -> None:
    """Record an answer or skip and create only draft evidence."""
    if skip == (answer_text is not None):
        _input_error("Provide exactly one of --answer or --skip.")
    try:
        repository = _repository(database)
        _required_profile(repository, candidate_id)
        selected = _find_question(repository, candidate_id, question_id)
        interview_answer = InterviewAnswer(
            question_id=question_id,
            answer=answer_text,
            skipped=skip,
        )
        outcome = AdaptiveInterview().record_answer(
            selected,
            interview_answer,
            evidence_id=f"EVID_INTERVIEW_{uuid4().hex[:16].upper()}",
            event_id=f"EVENT_{uuid4().hex.upper()}",
            created_at=datetime.now(UTC),
        )
        repository.save_interview_outcome(outcome)
        _emit(outcome)
    except (JobAgentError, ValidationError) as error:
        if isinstance(error, JobAgentError):
            _fail(error)
        _input_error("Interview answer is invalid.")


@candidate_app.command("confirm")
def confirm(
    candidate_id: str,
    evidence_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Explicitly confirm one admissible evidence item."""
    try:
        confirmed = CandidateEvidenceService(_repository(database)).confirm(
            candidate_id,
            evidence_id,
        )
        _emit(confirmed)
    except JobAgentError as error:
        _fail(error)


@candidate_app.command("status")
def status(
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    target_role: Annotated[str | None, typer.Option("--target-role")] = None,
) -> None:
    """Report profile completeness, gaps, and evidence readiness."""
    try:
        repository = _repository(database)
        profile = _required_profile(repository, candidate_id)
        result = CandidateReadinessService().evaluate(
            profile,
            repository.list_evidence(candidate_id),
            target_role=target_role,
        )
        _emit(result)
    except JobAgentError as error:
        _fail(error)


def _find_question(
    repository: SqliteCandidateRepository,
    candidate_id: str,
    question_id: str,
) -> InterviewQuestion:
    events = repository.list_interview_events(candidate_id)
    for event in reversed(events):
        if event.event_type is not InterviewEventType.QUESTION or event.question_id != question_id:
            continue
        payload: Any = event.payload.get("question")
        try:
            return InterviewQuestion.model_validate(payload)
        except ValidationError as error:
            raise ContractValidationError(
                "Stored interview question is invalid.",
                details={"candidate_id": candidate_id, "question_id": question_id},
            ) from error
    raise ContractValidationError(
        "Interview question was not found.",
        details={"candidate_id": candidate_id, "question_id": question_id},
    )
