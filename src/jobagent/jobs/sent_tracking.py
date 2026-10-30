"""Source-bound state transitions and read-only check cadence; never sends."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Never

from pydantic import HttpUrl

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.pipeline import SILENCE_LIMIT
from jobagent.outreach.service import OutreachService, policy_digest
from jobagent.schemas.conversation import Conversation, ConversationEvent, EventKind, ReplyResult
from jobagent.schemas.lexicon import JDFeatureSet
from jobagent.schemas.outreach import OutreachApproval, OutreachAudit, OutreachBatch, OutreachResult
from jobagent.schemas.sent_tracking import (
    SentProof,
    SentTrackingRecord,
    TrackingEventInput,
    TrackingHistoryEvent,
    TrackingState,
)

S = TrackingState
ACTIVE = frozenset({S.SENT, S.AWAITING_REPLY, S.REPLIED, S.SCREENING, S.INTERVIEW})
CHECK_INTERVAL = timedelta(hours=4)


def tracking_deadline(state: SentTrackingRecord) -> datetime:
    return (
        max(t for t in (state.sent_at, state.read_at, state.last_substantive_at) if t is not None)
        + SILENCE_LIMIT
    )


def next_observation(state: SentTrackingRecord, now: datetime) -> datetime:
    return max(now, min(now + CHECK_INTERVAL, tracking_deadline(state)))



def check_due_at(state: SentTrackingRecord) -> datetime | None:
    """Cap legacy cached schedules while respecting the actual bootstrap poll."""
    if state.next_check_at is None:
        return None
    due_at = min(state.next_check_at, tracking_deadline(state))
    if state.check_count == 0 and state.bootstrap_next_check_at is not None:
        due_at = max(due_at, state.bootstrap_next_check_at)
    return due_at


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


def outreach_proof(
    batch: OutreachBatch, approval: OutreachApproval, audit: OutreachAudit, readback_text: str
) -> SentProof:
    item = next((item for item in batch.items if item.number == audit.number), None)
    if item is None or not (
        audit.result is OutreachResult.SENT
        and audit.batch_id == batch.batch_id
        and approval.batch_id == batch.batch_id
        and approval.batch_digest == batch.batch_digest
        and batch.batch_digest == canonical_digest([[i.number, i.item_digest] for i in batch.items])
        and approval.policy_digest == batch.policy_digest == policy_digest(batch.policy)
        and audit.approval_id == approval.approval_id
        and audit.approval_channel == approval.channel
        and audit.number in approval.approved_numbers
        and audit.item_digest == item.item_digest
        and audit.job_id == item.job_id
        and audit.platform == item.platform
    ):
        _reject("Tracking requires a matching approved item and an existing sent audit.")
    assert item is not None
    if readback_text != item.text:
        raise ContractValidationError(
            "Readback does not match approved text.", details={"reason": "readback_mismatch"}
        )
    if audit.recorded_at.tzinfo is None or approval.approved_at.tzinfo is None:
        _reject("Send evidence needs timezone-aware timestamps.")
    if audit.recorded_at < approval.approved_at:
        _reject("A send audit cannot precede approval.")
    return SentProof(
        send_reference=audit.audit_id,
        job_id=item.job_id,
        job_url=HttpUrl(item.url),
        platform=item.platform,
        sent_text_hash=text_digest(item.text),
        sent_at=audit.recorded_at,
    )


def reply_proof(
    conversation: Conversation,
    events: list[ConversationEvent],
    result_event_id: str,
    readback_text: str,
    job_url: str,
) -> SentProof:
    result = next((e for e in events if e.event_id == result_event_id), None)
    if result is None or result.kind != EventKind.REPLY_RESULT or result.result != ReplyResult.SENT:
        _reject("Tracking needs a recorded successful reply.")
    approval = next(
        (
            e
            for e in reversed(events)
            if e.kind == EventKind.REPLY_APPROVED
            and e.seq < result.seq
            and e.reply_digest == result.reply_digest
        ),
        None,
    )
    if (
        approval is None
        or approval.reply is None
        or not approval.attestation
        or not approval.ask_id
        or conversation.job_id is None
    ):
        _reject("The reply result has no bound human approval.")
    assert approval is not None and approval.reply is not None and conversation.job_id is not None
    if result.recorded_at.tzinfo is None or approval.recorded_at.tzinfo is None:
        _reject("Reply result needs timezone-aware timestamps.")
    expected = canonical_digest(
        {
            "conversation": conversation.conversation_id,
            **approval.reply.model_dump(mode="json"),
        }
    )
    if (
        result.conversation_id != conversation.conversation_id
        or approval.conversation_id != conversation.conversation_id
        or result.reply_digest != expected
        or result.recorded_at < approval.recorded_at
    ):
        _reject("Reply proof does not match its conversation and approval.")
    if readback_text != approval.reply.text:
        raise ContractValidationError(
            "Readback does not match approved reply.", details={"reason": "readback_mismatch"}
        )
    return SentProof(
        send_reference=result.event_id,
        job_id=conversation.job_id,
        job_url=HttpUrl(job_url),
        platform=conversation.platform,
        sent_text_hash=text_digest(readback_text),
        sent_at=result.recorded_at,
    )


def pending_execution(
    batch: OutreachBatch,
    approval: OutreachApproval,
    audits: list[OutreachAudit],
    *,
    lease_held: bool | dict[str, bool],
    now: datetime,
) -> dict[int, str]:
    """Project existing gates only; do not reserve, send, or create tracking."""
    result = {}
    finished = {a.number for a in audits if a.batch_id == batch.batch_id}
    for platform in sorted({item.platform for item in batch.items}):
        decision = OutreachService().next_item(
            batch,
            approval,
            platform=platform,
            audits=audits,
            lease_held=lease_held.get(platform, False)
            if isinstance(lease_held, dict)
            else lease_held,
            now=now,
        )
        for item in batch.items:
            if (
                item.platform == platform
                and item.number in approval.approved_numbers
                and item.number not in finished
            ):
                result[item.number] = (
                    S.LEASED.value
                    if (
                        decision.allowed
                        and decision.item is not None
                        and decision.item.number == item.number
                    )
                    else S.APPROVED_PENDING_EXECUTION.value
                )
    return result


def start_tracking(
    proof: SentProof,
    *,
    candidate_id: str,
    tracking_id: str,
    now: datetime,
    next_poll_at: datetime | None = None,
) -> list[TrackingHistoryEvent]:
    if now.tzinfo is None or proof.sent_at > now:
        _reject("A recorded send cannot be in the future.")
    if next_poll_at is not None and (next_poll_at.tzinfo is None or next_poll_at <= now):
        _reject("Bootstrap must name the actual next future poll.")
    if now > proof.sent_at + CHECK_INTERVAL and next_poll_at is None:
        _reject("Late registration needs next_poll_at; missed checks cannot be backfilled.")
    # Old missed_check_days values remain readable in history; no old cadence is inferred.
    state = SentTrackingRecord(
        registered_at=now,
        bootstrap_next_check_at=next_poll_at,
        tracking_id=tracking_id,
        candidate_id=candidate_id,
        job_id=proof.job_id,
        job_url=proof.job_url,
        platform=proof.platform,
        sent_text_hash=proof.sent_text_hash,
        sent_at=proof.sent_at,
        tracking_state=S.SENT,
        tracking_version=1,
        send_references=[proof.send_reference],
        last_event_at=now,
    )
    digest = canonical_digest(
        [candidate_id, tracking_id, proof.model_dump(mode="json")]
        + ([next_poll_at.isoformat()] if next_poll_at else [])
    )
    first = TrackingHistoryEvent(
        event_id=tracking_id + ":sent",
        tracking_id=tracking_id,
        version=1,
        kind="sent",
        occurred_at=now,
        evidence_reference=proof.send_reference,
        input_digest=digest,
        state=state,
    )
    awaiting = state.model_copy(
        update={
            "tracking_state": S.AWAITING_REPLY,
            "tracking_version": 2,
            "next_check_at": next_poll_at or proof.sent_at + CHECK_INTERVAL,
        }
    )
    second = TrackingHistoryEvent(
        event_id=tracking_id + ":readback",
        tracking_id=tracking_id,
        version=2,
        kind="readback_confirmed",
        occurred_at=now,
        evidence_reference=proof.send_reference,
        input_digest=digest,
        state=awaiting,
    )
    return [first, second]


def _step(
    state: SentTrackingRecord,
    event: TrackingEventInput,
    suffix: str = "",
    kind: str | None = None,
    /,
    **updates: object,
) -> TrackingHistoryEvent:
    observations = list(state.observation_ids)
    key = event.kind + ":" + event.observation_id
    if key not in observations:
        observations.append(key)
    result = SentTrackingRecord.model_validate(
        {
            **state.model_dump(),
            **updates,
            "last_event_at": event.observed_at,
            "tracking_version": state.tracking_version + 1,
            "observation_ids": observations,
        }
    )
    return TrackingHistoryEvent(
        event_id=event.event_id + suffix,
        tracking_id=state.tracking_id,
        version=result.tracking_version,
        kind=kind or event.kind,
        occurred_at=event.observed_at,
        evidence_reference=event.evidence_reference,
        input_digest=canonical_digest(event.model_dump(mode="json")),
        state=result,
    )


def _close(
    state: SentTrackingRecord,
    event: TrackingEventInput,
    target: TrackingState,
    reason: str,
    outcome: str | None = None,
    **updates: object,
) -> list[TrackingHistoryEvent]:
    first = _step(
        state,
        event,
        tracking_state=target,
        next_check_at=None,
        paused=False,
        abandoned_at=event.observed_at,
        abandon_reason=reason,
        outcome=outcome,
        **updates,
    )
    second = _step(first.state, event, ":closed", "closed", tracking_state=S.CLOSED)
    return [first, second]


def _owner(event: TrackingEventInput) -> None:
    if (
        event.evidence_kind != "owner_message"
        or not event.owner_text
        or not event.owner_text.strip()
    ):
        _reject("This decision requires the actual owner's words and source reference.")


def _inbound(
    state: SentTrackingRecord,
    event: TrackingEventInput,
    conversation: Conversation | None,
    inbound: ConversationEvent | None,
) -> None:
    if event.evidence_kind not in {"conversation_message", "list_message"}:
        _reject("Unread counters are not confirmed recruiter messages.")
    if conversation is None or inbound is None or inbound.inbound is None:
        _reject("A confirmed message needs an existing conversation inbound event.")
    assert conversation is not None and inbound is not None and inbound.inbound is not None
    if (
        inbound.recorded_at.tzinfo is None
        or inbound.inbound.received_at.tzinfo is None
        or not state.sent_at <= inbound.recorded_at <= event.observed_at
        or not state.sent_at <= inbound.inbound.received_at <= event.observed_at
    ):
        _reject("The recruiter message must be new in this send round and already observed.")
    if not (
        conversation.job_id == state.job_id
        and conversation.platform == state.platform
        and conversation.conversation_id == event.conversation_id == inbound.conversation_id
        and inbound.kind == EventKind.INBOUND
        and inbound.event_id == event.inbound_event_id == event.evidence_reference
    ):
        _reject("The inbound evidence belongs to another target or event.")


def advance(
    state: SentTrackingRecord,
    event: TrackingEventInput,
    *,
    now: datetime,
    conversation: Conversation | None = None,
    inbound: ConversationEvent | None = None,
    reply_proof: SentProof | None = None,
) -> list[TrackingHistoryEvent]:
    if (
        event.tracking_id != state.tracking_id
        or event.candidate_id != state.candidate_id
        or event.expected_version != state.tracking_version
    ):
        _reject("Tracking changed or belongs to another candidate.")
    if now.tzinfo is None or not state.last_event_at <= event.observed_at <= now:
        _reject("Tracking observations must be chronological and not in the future.")
    if event.kind + ":" + event.observation_id in state.observation_ids:
        _reject("This observation has already been applied.")
    if event.kind == "anomaly":
        if event.evidence_kind not in {"platform_state", "send_audit"}:
            _reject("An anomaly needs platform or readback evidence.")
        return [_step(state, event, paused=True, next_check_at=None)]
    if state.tracking_state not in ACTIVE:
        _reject("Closed tracking cannot be revived; a new approved send needs a new record.")
    if event.kind == "resume":
        _owner(event)
        if not state.paused:
            _reject("Tracking is not paused.")
        next_at = next_observation(state, now)
        if state.check_count == 0 and state.bootstrap_next_check_at is not None:
            next_at = max(next_at, state.bootstrap_next_check_at)
        return [_step(state, event, paused=False, next_check_at=next_at)]
    if state.paused and event.kind not in {"user_abandon", "queue_closed"}:
        _reject("Tracking is paused until the owner explicitly resumes it.")
    if event.kind in {"user_abandon", "queue_closed"}:
        _owner(event)
        return _close(state, event, S.ABANDONED_BY_USER, event.kind)
    if event.kind == "job_closed":
        if event.evidence_kind not in {"detail_page", "list_status"} or (
            event.job_url != state.job_url
        ):
            _reject("Job closure needs a matching detail/list observation.")
        return _close(state, event, S.JOB_CLOSED, "job_closed")
    if event.kind == "suspected_reply":
        if state.tracking_state != S.AWAITING_REPLY:
            _reject("Only an awaiting record can receive a suspected reply.")
        return [_step(state, event)]
    if event.kind == "read_confirmed":
        if (
            event.evidence_kind not in {"conversation_message", "list_message"}
            or event.job_url != state.job_url
            or state.read_at is not None
        ):
            _reject("A read needs actual target-bound evidence and can only start its clock once.")
        updated = state.model_copy(update={"read_at": event.observed_at})
        return [
            _step(
                state,
                event,
                read_at=event.observed_at,
                next_check_at=next_observation(updated, event.observed_at),
            )
        ]
    if event.kind == "no_reply":
        if state.tracking_state not in ACTIVE or event.evidence_kind not in {
            "conversation_message",
            "list_message",
        }:
            _reject("No-reply checks need an awaiting record and actual message observation.")
        due_at = check_due_at(state)
        if due_at is None or event.observed_at < due_at:
            _reject("This check is not due; catch-up checks cannot be compressed.")
        count = state.check_count + 1
        if event.observed_at >= tracking_deadline(state):
            return _close(
                state,
                event,
                S.NO_RESPONSE_EXPIRED,
                "read_no_reply_2d" if state.read_at is not None else "no_reply_2d",
                "no_response",
                check_count=count,
                last_checked_at=event.observed_at,
            )
        next_at = next_observation(state, event.observed_at)
        return [
            _step(
                state,
                event,
                check_count=count,
                last_checked_at=event.observed_at,
                next_check_at=next_at,
            )
        ]
    if event.kind == "reply_sent":
        if state.tracking_state not in {S.REPLIED, S.SCREENING, S.INTERVIEW}:
            _reject("A new reply round requires a confirmed recruiter response.")
        if reply_proof is None or not (
            reply_proof.job_id == state.job_id
            and reply_proof.platform == state.platform
            and reply_proof.job_url == state.job_url
            and reply_proof.send_reference not in state.send_references
            and state.sent_at <= reply_proof.sent_at <= event.observed_at
            and event.evidence_kind == "send_audit"
            and reply_proof.send_reference
            == event.reply_result_event_id
            == event.evidence_reference
        ):
            _reject("A new waiting round needs a fresh bound approved-send readback.")
        next_state = S.AWAITING_REPLY if state.tracking_state == S.REPLIED else state.tracking_state
        return [
            _step(
                state,
                event,
                tracking_state=next_state,
                sent_at=reply_proof.sent_at,
                sent_text_hash=reply_proof.sent_text_hash,
                round_number=state.round_number + 1,
                missed_check_days=[],
                bootstrap_next_check_at=None,
                registered_at=now,
                check_count=0,
                last_checked_at=None,
                read_at=None,
                last_substantive_at=None,
                reply_detected_at=None,
                next_check_at=reply_proof.sent_at + CHECK_INTERVAL,
                send_references=[*state.send_references, reply_proof.send_reference],
            )
        ]
    _inbound(state, event, conversation, inbound)
    assert inbound is not None and inbound.inbound is not None
    actual_activity = inbound.inbound.received_at
    substantive_at = max(t for t in (state.last_substantive_at, actual_activity) if t is not None)
    activity_state = state.model_copy(update={"last_substantive_at": substantive_at})
    if event.kind == "substantive_reply":
        return [
            _step(
                state,
                event,
                last_substantive_at=substantive_at,
                next_check_at=next_observation(activity_state, event.observed_at),
            )
        ]
    if event.kind == "reply_confirmed":
        if state.tracking_state != S.AWAITING_REPLY:
            _reject("Only awaiting tracking can confirm its first reply.")
        return [
            _step(
                state,
                event,
                tracking_state=S.REPLIED,
                reply_kind="message",
                reply_detected_at=actual_activity,
                last_substantive_at=substantive_at,
                next_check_at=next_observation(activity_state, event.observed_at),
            )
        ]
    if event.kind == "screening_confirmed":
        if state.tracking_state != S.REPLIED or not (
            inbound.inbound.asks_resume
            or (event.evidence_excerpt and event.evidence_excerpt in inbound.inbound.text)
        ):
            _reject("Screening needs a confirmed reply and explicit progression evidence.")
        return [
            _step(
                state,
                event,
                tracking_state=S.SCREENING,
                reply_kind="screening",
                outcome="screening",
                last_substantive_at=substantive_at,
                next_check_at=next_observation(activity_state, event.observed_at),
            )
        ]
    if event.kind == "interview_confirmed":
        if state.tracking_state not in {S.REPLIED, S.SCREENING} or (
            not inbound.inbound.interview_invite
        ):
            _reject("Interview cannot skip confirmed reply/progression evidence.")
        return [
            _step(
                state,
                event,
                tracking_state=S.INTERVIEW,
                reply_kind="interview",
                outcome="interview",
                last_substantive_at=substantive_at,
                next_check_at=next_observation(activity_state, event.observed_at),
            )
        ]
    if event.kind == "employer_rejected":
        if not inbound.inbound.declined:
            _reject("Rejection needs an explicit recruiter decline.")
        return _close(state, event, S.REJECTED, "rejected", "rejected")
    _reject("Illegal tracking transition.")


def tracking_report(
    records: list[SentTrackingRecord], feature_sets: list[JDFeatureSet]
) -> dict[str, object]:
    latest: dict[str, JDFeatureSet] = {}
    for feature_set in feature_sets:
        if feature_set.job_id not in latest or (
            feature_set.snapshot_version > latest[feature_set.job_id].snapshot_version
        ):
            latest[feature_set.job_id] = feature_set
    negative: dict[str, set[str]] = {}
    for state in records:
        features = latest.get(state.job_id)
        if state.outcome not in {"no_response", "rejected"} or features is None:
            continue
        for feature in features.features:
            if feature.polarity == "positive":
                negative.setdefault(feature.term, set()).add(state.job_id)
    return {
        "counts": dict(Counter(state.tracking_state.value for state in records)),
        "records": [state.model_dump(mode="json") for state in records],
        "negative_patterns": [
            {
                "feature": term,
                "distinct_jobs": len(jobs),
                "job_ids": sorted(jobs),
                "meaning": "observation_only_owner_review_required",
            }
            for term, jobs in sorted(negative.items())
            if len(jobs) >= 3
        ],
        "positive_observations": [
            {"job_id": state.job_id, "outcome": state.outcome}
            for state in records
            if state.outcome in {"screening", "interview"}
        ],
        "changes_search_weights": False,
    }
