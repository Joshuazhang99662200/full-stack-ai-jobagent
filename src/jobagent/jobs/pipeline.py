"""Pure evidence-bound pipeline transitions and a single silence clock."""

from datetime import datetime, timedelta

from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.schemas.pipeline import (
    PipelineHistory,
    PipelineJob,
    PipelineMeta,
    PipelineObservation,
    PipelineReason,
    PipelineTransition,
    PipelineVerifiedEvidence,
)

SILENCE_LIMIT = timedelta(hours=48)


def silence_deadline(job: PipelineJob, meta: PipelineMeta) -> datetime | None:
    if (
        meta.paused
        or meta.proof_status != "verified"
        or job.sent_at is None
        or job.pipeline_state in {"draft_pending", "abandoned", "interviewed"}
    ):
        return None
    times = [
        t
        for t in (job.sent_at, meta.read_at, meta.last_substantive_at, job.resume_sent_at)
        if t is not None
    ]
    return max(times) + SILENCE_LIMIT


def context(
    job: PipelineJob, meta: PipelineMeta, candidate: str, version: int, at: datetime, now: datetime
) -> None:
    if (
        candidate != job.candidate_id
        or version != meta.version
        or meta.pipeline_id != job.pipeline_id
    ):
        reject("Pipeline changed or belongs to another candidate.")
    if not job.updated_at <= at <= now or now.tzinfo is None:
        reject("Pipeline evidence must be chronological and already observed.")
    if job.pipeline_state == "abandoned":
        reject("Abandoned contact rounds cannot be revived.")


def advance_pipeline(
    job: PipelineJob,
    meta: PipelineMeta,
    event: PipelineTransition,
    proof: PipelineVerifiedEvidence,
    *,
    now: datetime,
) -> tuple[PipelineJob, PipelineMeta, PipelineHistory]:
    context(job, meta, event.candidate_id, event.expected_version, event.changed_at, now)
    if event.pipeline_id != job.pipeline_id or event.from_state != job.pipeline_state:
        reject("Transition must bind the current source state and contact round.")
    if (
        proof.reference != event.evidence_reference
        or proof.kind != event.evidence_kind
        or proof.observed_at != event.changed_at
        or proof.source_at > event.changed_at
    ):
        reject("Evidence does not match the requested transition.")
    closure = event.to_state == "abandoned"
    if meta.paused and not (closure and event.reason_code in {"job_closed", "user_abandoned"}):
        reject("Pipeline is paused until the owner resumes it.")
    if (
        event.from_state != "draft_pending"
        and meta.proof_status != "verified"
        and not (closure and event.reason_code in {"job_closed", "user_abandoned"})
    ):
        reject("Legacy send declaration is proof_pending; it cannot advance or expire.")
    changes: dict[str, object] = {
        "pipeline_state": event.to_state,
        "state_reason": event.reason_code,
        "state_changed_at": event.changed_at,
        "updated_at": event.changed_at,
    }
    extra: dict[str, object] = {
        "version": meta.version + 1,
        "last_evidence_reference": proof.reference,
    }
    if event.to_state == "greeting_sent":
        if (
            event.evidence_kind != "send_audit"
            or not proof.sent_text
            or not proof.sent_at
            or not proof.send_reference
            or proof.sent_at > event.changed_at
            or proof.sent_at < job.entered_at
            or proof.sent_text != job.draft_greeting
            or text_digest(proof.sent_text) != job.draft_digest
        ):
            reject("Greeting needs an existing exact approved-send readback of this draft.")
        changes.update(
            sent_greeting=proof.sent_text,
            sent_text_hash=text_digest(proof.sent_text),
            sent_at=proof.sent_at,
            send_readback="exact",
        )
        extra.update(proof_status="verified", sent_greeting_version=proof.greeting_version)
    elif event.to_state == "greeting_read":
        if not proof.read_confirmed or proof.kind not in {"conversation_message", "list_message"}:
            reject("Read state needs confirmed conversation evidence.")
        extra["read_at"] = proof.source_at
    elif event.to_state in {"initial_contact", "resume_requested", "interview_pending"}:
        if not proof.substantive_reply or proof.kind not in {
            "conversation_message",
            "list_message",
        }:
            reject("A recruiter transition needs a confirmed substantive inbound message.")
        if event.to_state == "resume_requested":
            if not proof.asks_resume:
                reject("A resume request must be explicit in the confirmed inbound evidence.")
            changes.update(
                resume_requested=True,
                resume_requested_at=proof.source_at,
                resume_request_evidence=proof.reference,
            )
        if event.to_state == "interview_pending" and not proof.interview_invite:
            reject("Interview pending requires the actual invitation.")
        extra["last_substantive_at"] = max(
            t for t in (meta.last_substantive_at, proof.source_at) if t is not None
        )
    elif event.to_state == "resume_sent":
        if (
            proof.kind != "send_audit"
            or not proof.sent_at
            or not proof.resume_version
            or not proof.resume_file_id
            or not proof.send_reference
        ):
            reject("Resume send needs an approved custom attachment and exact readback.")
        changes.update(
            resume_version=proof.resume_version,
            resume_file_id=proof.resume_file_id,
            resume_sent_at=proof.sent_at,
        )
    elif event.to_state == "interviewed":
        if not proof.interview_completed:
            reject("An invitation is not evidence of interview completion.")
        extra["last_substantive_at"] = proof.source_at
    if closure:
        reason = event.reason_code
        if reason in {"read_no_reply_2d", "no_reply_2d"}:
            deadline = silence_deadline(job, meta)
            expected = "read_no_reply_2d" if meta.read_at is not None else "no_reply_2d"
            if (
                deadline is None
                or event.changed_at < deadline
                or reason != expected
                or proof.kind not in {"conversation_message", "list_message"}
            ):
                reject(
                    "Silence expiry needs a real current check after the evidence-bound deadline."
                )
        elif reason == "employer_rejected" and not proof.employer_rejected:
            reject("Employer rejection requires an explicit confirmed message.")
        elif reason == "job_closed" and not proof.job_closed:
            reject("Job closure must be verified on its actual page.")
        elif reason == "user_abandoned" and not proof.owner_decision:
            reject("Abandonment requires the owner's actual decision.")
        extra.update(
            abandoned_at=event.changed_at,
            last_checked_at=event.changed_at,
            paused=False,
            pause_reason=None,
        )
    updated = PipelineJob.model_validate({**job.model_dump(), **changes})
    metadata = PipelineMeta.model_validate({**meta.model_dump(), **extra})
    history = PipelineHistory(
        history_id="PH_" + canonical_digest([job.pipeline_id, event.event_id])[7:31].upper(),
        pipeline_id=job.pipeline_id,
        from_state=job.pipeline_state,
        to_state=event.to_state,
        changed_at=event.changed_at,
        evidence_kind=event.evidence_kind,
        evidence_reference=event.evidence_reference,
        reason_code=event.reason_code,
    )
    return updated, metadata, history


def observe_pipeline(
    job: PipelineJob,
    meta: PipelineMeta,
    event: PipelineObservation,
    *,
    now: datetime,
    proof: PipelineVerifiedEvidence | None = None,
) -> tuple[PipelineJob, PipelineMeta, PipelineHistory | None]:
    context(job, meta, event.candidate_id, event.expected_version, event.observed_at, now)
    if event.pipeline_id != job.pipeline_id:
        reject("Observation belongs to another contact round.")
    extra: dict[str, object] = {
        "version": meta.version + 1,
        "last_evidence_reference": event.evidence_reference,
    }
    if event.kind == "pause":
        if event.evidence_kind not in {"platform_state", "send_audit"}:
            reject("Pause needs actual login, risk or readback evidence.")
        extra.update(paused=True, pause_reason=event.evidence_reference)
    elif event.kind == "resume":
        if (
            event.evidence_kind != "owner_message"
            or not event.owner_text
            or not event.owner_text.strip()
        ):
            reject("Resume requires the owner's original reply.")
        extra.update(paused=False, pause_reason=None)
    else:
        if meta.paused:
            reject("Paused records cannot be checked until the owner resumes them.")
        if event.kind == "no_reply":
            if (
                event.evidence_kind not in {"conversation_message", "list_message"}
                or meta.proof_status != "verified"
            ):
                reject("Silence requires a real loaded conversation and verified send time.")
            deadline = silence_deadline(job, meta)
            if deadline is None:
                reject("This state is not awaiting a silence check.")
            if event.observed_at >= deadline:
                reason: PipelineReason = (
                    "read_no_reply_2d" if meta.read_at is not None else "no_reply_2d"
                )
                transition = PipelineTransition(
                    event_id=event.event_id,
                    pipeline_id=job.pipeline_id,
                    candidate_id=event.candidate_id,
                    expected_version=event.expected_version,
                    from_state=job.pipeline_state,
                    to_state="abandoned",
                    changed_at=event.observed_at,
                    evidence_kind=event.evidence_kind,
                    evidence_reference=event.evidence_reference,
                    reason_code=reason,
                )
                checked = PipelineVerifiedEvidence(
                    reference=event.evidence_reference,
                    kind=event.evidence_kind,
                    observed_at=event.observed_at,
                    source_at=event.observed_at,
                )
                return advance_pipeline(job, meta, transition, checked, now=now)
            extra["last_checked_at"] = event.observed_at
        elif event.kind == "substantive_reply":
            if (
                meta.proof_status != "verified"
                or proof is None
                or not proof.substantive_reply
                or proof.reference != event.evidence_reference
                or proof.source_at > event.observed_at
            ):
                reject("Activity reset requires a real, bound recruiter reply.")
            extra["last_substantive_at"] = max(
                t for t in (meta.last_substantive_at, proof.source_at) if t is not None
            )
    return (
        PipelineJob.model_validate({**job.model_dump(), "updated_at": event.observed_at}),
        PipelineMeta.model_validate({**meta.model_dump(), **extra}),
        None,
    )
