"""Read-only, candidate-scoped context for whole-message greeting generation."""

import hashlib
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.outreach.generation import content_digest
from jobagent.outreach.service import policy_digest
from jobagent.schemas.candidate import CandidateProfile, EvidenceItem
from jobagent.schemas.greeting import (
    GreetingInterest,
    GreetingJob,
    GreetingRequest,
    GreetingSettings,
)
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.outreach import OutreachApproval, OutreachAsk, OutreachBatch, OutreachItem
from jobagent.schemas.sourcing_feedback import PagedCardState, SourcingFeedback
from jobagent.skill_resources import read_reference

_INCOMPLETE = frozenset({
    "JD_MISSING", "MISSING_JD", "JD_TRUNCATED", "TRUNCATED_JD", "LISTING_ONLY",
    "JD_INCOMPLETE", "INCOMPLETE_JD", "JD_SUMMARY_ONLY", "SUMMARY_ONLY",
})
_SYNTHETIC = ("mock", "demo", "synthetic", "fixture", "test")


def _real_job(job: NormalizedJob) -> bool:
    source = job.source.lower()
    host = (urlsplit(str(job.url)).hostname or "").lower()
    if any(source.startswith(word) for word in _SYNTHETIC):
        return False
    return not (
        host in {"example.com", "example.org", "example.net", "localhost"}
        or host.endswith((".example", ".test", ".invalid"))
        or any(host.endswith("." + domain) for domain in
               ("example.com", "example.org", "example.net"))
    )


def _full_job(job: NormalizedJob) -> bool:
    return bool(job.jd_raw.strip()) and not (_INCOMPLETE & {w.upper() for w in job.warnings})


def _job_view(job: NormalizedJob) -> GreetingJob:
    return GreetingJob(
        job_id=job.id, company=job.company, title=job.title,
        platform=job.source, url=str(job.url), jd_raw=job.jd_raw,
    )


def _owned(item: OutreachItem, evidence_ids: set[str]) -> bool:
    return bool(item.evidence_ids) and set(item.evidence_ids) <= evidence_ids


def _valid_binding(batch: OutreachBatch, ask: OutreachAsk, approval: OutreachApproval) -> bool:
    if (approval.batch_id != batch.batch_id or ask.batch_id != batch.batch_id
            or approval.ask_id != ask.ask_id
            or approval.batch_digest != batch.batch_digest
            or ask.batch_digest != batch.batch_digest
            or approval.policy_digest != batch.policy_digest
            or ask.policy_digest != batch.policy_digest
            or policy_digest(batch.policy) != batch.policy_digest
            or ask.asked_at > approval.approved_at
            or batch.created_at > ask.asked_at):
        return False
    # Recompute the same item-digest list used by OutreachService, without treating
    # today's job text as the text the owner saw historically.
    if content_digest([[x.number, x.item_digest] for x in batch.items]) != batch.batch_digest:
        return False
    numbers = {item.number for item in batch.items}
    return (set(approval.approved_numbers) <= numbers
            and all(item.text in ask.question for item in batch.items
                    if item.number in approval.approved_numbers))


def _history(
    connection: sqlite3.Connection,
    jobs: Mapping[str, NormalizedJob],
    owned_ids: set[str],
) -> tuple[list[GreetingInterest], list[str]]:
    interests: list[GreetingInterest] = []
    feedback: list[str] = []
    seen: set[str] = set()
    rows = connection.execute(
        "SELECT a.approval_json, b.batch_json, q.ask_json "
        "FROM outreach_approvals a JOIN outreach_batches b ON a.batch_id = b.batch_id "
        "JOIN outreach_asks q ON q.ask_id = json_extract(a.approval_json, '$.ask_id') "
        "ORDER BY json_extract(a.approval_json, '$.approved_at') DESC, a.approval_id DESC"
    )
    for row in rows:
        try:
            approval = OutreachApproval.model_validate_json(row[0])
            batch = OutreachBatch.model_validate_json(row[1])
            ask = OutreachAsk.model_validate_json(row[2])
        except ValidationError:
            continue
        if not _valid_binding(batch, ask, approval):
            continue
        for item in batch.items:
            job = jobs.get(item.job_id)
            if (item.number not in approval.approved_numbers or not _owned(item, owned_ids)
                    or job is None or not _real_job(job) or not _full_job(job)):
                continue
            if item.written_by == "person" and len(feedback) < 12:
                feedback.append(f"{approval.approval_id}: owner_edit: {item.text}")
            if item.job_id not in seen and len(interests) < 16:
                interests.append(GreetingInterest(job=_job_view(job),
                                                  selection_id=approval.approval_id))
                seen.add(item.job_id)
    return interests, feedback


def _card_feedback(
    connection: sqlite3.Connection,
    candidate_id: str,
    jobs: Mapping[str, NormalizedJob],
    owned_ids: set[str],
) -> list[str]:
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if not {"sourcing_feedback_events", "paged_card_events", "paged_card_states"} <= tables:
        return []
    rows = connection.execute(
        "SELECT f.event_json, s.state_json, b.batch_json, q.ask_json "
        "FROM sourcing_feedback_events f "
        "JOIN paged_card_events e ON e.event_id = f.event_id "
        "JOIN paged_card_states s ON s.message_id = e.message_id "
        "JOIN outreach_batches b ON b.batch_id = json_extract(s.state_json, '$.batch_id') "
        "JOIN outreach_asks q ON q.ask_id = json_extract(s.state_json, '$.ask_id') "
        "ORDER BY f.occurred_at DESC, f.event_id DESC"
    )
    result = []
    for row in rows:
        try:
            event = SourcingFeedback.model_validate_json(row[0])
            state = PagedCardState.model_validate_json(row[1])
            batch = OutreachBatch.model_validate_json(row[2])
            ask = OutreachAsk.model_validate_json(row[3])
        except ValidationError:
            continue
        job = jobs.get(event.job_id)
        if (state.candidate_id != candidate_id or state.demo_mode or job is None
                or (event.candidate_id is not None and event.candidate_id != candidate_id)
                or not _real_job(job) or ask.batch_id != batch.batch_id
                or ask.batch_digest != batch.batch_digest
                or ask.policy_digest != batch.policy_digest):
            continue
        for item in batch.items:
            words = state.drafts.get(str(item.number), item.text)
            # A card event is useful as feedback only when its provenance binds
            # the same candidate, exact words, source, job and recorded decision.
            if (item.job_id != event.job_id or item.platform != event.source
                    or not _owned(item, owned_ids)
                    or (event.original_text is not None and event.original_text != item.text)
                    or (event.action == "revise" and event.revised_text != words)
                    or state.decisions.get(str(item.number)) != {
                        "approve": "approved", "revise": "revision_requested",
                        "decline": "declined",
                    }[event.action]
                    or "sha256:" + hashlib.sha256(words.encode()).hexdigest()
                    != event.content_digest):
                continue
            note = (f"{event.event_id}: {event.action}/{event.reason_category}: "
                    f"{event.free_text}")
            if event.original_text is not None:
                note += "\nOriginal greeting: " + event.original_text
            if event.revised_text is not None:
                note += "\nOwner revision: " + event.revised_text
            result.append(note)
            break
        if len(result) >= 8:
            break
    return result


def load_greeting_request(
    database: Path,
    settings: GreetingSettings,
    *,
    job_id: str | None = None,
    feedback: str | None = None,
) -> GreetingRequest:
    """Load an immutable snapshot; no migrations, writes, approvals or sends."""
    settings = GreetingSettings.model_validate(settings.model_dump())
    if not database.is_file():
        raise ContractValidationError("Greeting generation needs an existing private database.")
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT profile_json FROM candidate_profiles WHERE candidate_id = ?",
                (settings.candidate_id,),
            ).fetchone()
            if row is None:
                raise ContractValidationError("The requested candidate does not exist.")
            profile = CandidateProfile.model_validate_json(row[0])
            if profile.id != settings.candidate_id:
                raise ContractValidationError("The candidate profile has inconsistent ownership.")
            evidence = [EvidenceItem.model_validate_json(row[0]) for row in connection.execute(
                "SELECT evidence_json FROM evidence_items WHERE candidate_id = ? "
                "ORDER BY evidence_id", (settings.candidate_id,),
            )]
            by_id = {item.id: item for item in evidence}
            for correction in settings.corrections:
                old = by_id.get(correction.older_id)
                current = by_id.get(correction.replacement_id)
                if (old is None or current is None or not current.user_confirmed
                        or current.confidence.value == "weak"
                        or correction.replacement_excerpt not in current.statement):
                    raise ContractValidationError(
                        "A correction has no exact owned confirmed source."
                    )
            older_ids = {correction.older_id for correction in settings.corrections}
            current_evidence = [item for item in evidence if item.user_confirmed
                                and item.confidence.value != "weak" and item.id not in older_ids]
            jobs = {job.id: job for job in (
                NormalizedJob.model_validate_json(row[0]) for row in connection.execute(
                    "SELECT job_json FROM normalized_jobs ORDER BY job_id"
                )
            )}
            historical_ids = {item.id for item in evidence if item.user_confirmed
                              and item.confidence.value != "weak"}
            interests, notes = _history(connection, jobs, historical_ids)
            for selected in reversed(settings.selected_job_ids):
                selected_job = jobs.get(selected)
                if (selected_job is None or not _real_job(selected_job)
                        or not _full_job(selected_job)):
                    raise ContractValidationError("An owner-selected job lacks a real complete JD.")
                interests = [item for item in interests if item.job.job_id != selected]
                interests.insert(0, GreetingInterest(job=_job_view(selected_job),
                                                      selection_id="owner_selection:" + selected))
            interests = interests[:16]
            notes.extend(_card_feedback(connection, settings.candidate_id, jobs, historical_ids))
            if feedback and feedback.strip():
                notes.insert(0, feedback.strip())
            job = jobs.get(job_id) if job_id is not None else None
            if job_id is not None and (job is None or not _full_job(job)):
                raise ContractValidationError("Targeted generation requires a complete stored JD.")
            return GreetingRequest(
                candidate_id=settings.candidate_id, display_name=settings.display_name,
                mode="targeted" if job is not None else "default",
                job=_job_view(job) if job is not None else None,
                evidence=current_evidence, interests=interests, feedback=notes[:20],
                guidance=settings.guidance, corrections=settings.corrections,
                policy_digest=content_digest(read_reference("references/greeting-ai.md")),
            )
    except (sqlite3.Error, ValidationError, ValueError) as error:
        raise ContractValidationError(
            "The database cannot supply valid candidate-scoped greeting context.",
            details={"error_type": type(error).__name__},
        ) from None
