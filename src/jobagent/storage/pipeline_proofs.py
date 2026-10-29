"""Bind pipeline transitions to existing proofs; never creates an approval or sends.

Conversation receipt and host-page references are observations, not authentication
of an external browser. Host-attested captures must carry this exact target URL;
unread counts can never stand in for an observed receipt or recruiter message.
"""

from datetime import datetime

from pydantic import ValidationError

from jobagent.jobs.job_intake import reject
from jobagent.jobs.sent_tracking import outreach_proof, reply_proof
from jobagent.schemas.conversation import Conversation, ConversationEvent, EventKind, ReplyKind
from jobagent.schemas.pipeline import (
    PipelineJob,
    PipelineMeta,
    PipelineObservation,
    PipelineTransition,
    PipelineVerifiedEvidence,
)
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository


class PipelineProofResolver:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.conversations = SqliteConversationRepository(database)

    @staticmethod
    def _context(
        job: PipelineJob,
        meta: PipelineMeta,
        candidate: str,
        pipeline_id: str,
        observed_at: datetime,
        now: datetime,
    ) -> None:
        if (
            candidate != job.candidate_id
            or pipeline_id != job.pipeline_id
            or meta.pipeline_id != job.pipeline_id
        ):
            reject("Evidence must bind this candidate and resolved pipeline target.")
        if now.tzinfo is None or observed_at > now:
            reject("Evidence must have been observed already.")

    def _conversation(
        self, job: PipelineJob, meta: PipelineMeta, conversation_id: str | None
    ) -> tuple[Conversation, list[ConversationEvent]]:
        conversation = self.conversations.get_conversation(conversation_id or "")
        if (
            conversation is None
            or meta.normalized_job_id is None
            or conversation.job_id != meta.normalized_job_id
            or conversation.platform != job.platform
        ):
            reject("Conversation evidence belongs to another resolved job or platform.")
        return conversation, self.conversations.list_events(conversation.conversation_id)

    def _inbound(
        self,
        job: PipelineJob,
        meta: PipelineMeta,
        *,
        conversation_id: str | None,
        inbound_event_id: str | None,
        reference: str,
        kind: str,
        observed_at: datetime,
    ) -> PipelineVerifiedEvidence:
        if kind not in {"conversation_message", "list_message"}:
            reject("Unread counters and system state are not recruiter message evidence.")
        conversation, events = self._conversation(job, meta, conversation_id)
        event = next((e for e in events if e.event_id == inbound_event_id), None)
        if (
            event is None
            or event.kind != EventKind.INBOUND
            or event.inbound is None
            or event.event_id != reference
            or event.conversation_id != conversation.conversation_id
        ):
            reject("A substantive reply needs an existing, bound inbound event.")
        message = event.inbound
        if (
            job.sent_at is None
            or event.recorded_at.tzinfo is None
            or message.received_at.tzinfo is None
            or not job.sent_at <= message.received_at <= observed_at
            or not job.sent_at <= event.recorded_at <= observed_at
            or not message.text.strip()
        ):
            reject("Recruiter evidence must be new within this send round and already observed.")
        return PipelineVerifiedEvidence.model_validate(
            dict(
                reference=reference,
                kind=kind,
                observed_at=observed_at,
                source_at=message.received_at,
                substantive_reply=True,
                asks_resume=message.asks_resume,
                interview_invite=message.interview_invite,
                employer_rejected=message.declined,
            )
        )

    def inbound(
        self, job: PipelineJob, meta: PipelineMeta, event: PipelineObservation, *, now: datetime
    ) -> PipelineVerifiedEvidence:
        if not event.evidence_reference.strip():
            reject("An actual private evidence reference is required.")
        self._context(job, meta, event.candidate_id, event.pipeline_id, event.observed_at, now)
        return self._inbound(
            job,
            meta,
            conversation_id=event.conversation_id,
            inbound_event_id=event.inbound_event_id,
            reference=event.evidence_reference,
            kind=event.evidence_kind,
            observed_at=event.observed_at,
        )

    def resolve(
        self, job: PipelineJob, meta: PipelineMeta, event: PipelineTransition, *, now: datetime
    ) -> PipelineVerifiedEvidence:
        try:
            event = PipelineTransition.model_validate(event.model_dump())
        except ValidationError:
            reject("Invalid pipeline transition evidence contract.")
        if not event.evidence_reference.strip():
            reject("An actual private evidence reference is required.")
        self._context(job, meta, event.candidate_id, event.pipeline_id, event.changed_at, now)
        if event.from_state != job.pipeline_state or event.expected_version != meta.version:
            reject("Evidence must bind the current contact-round state and version.")
        if event.to_state == "greeting_sent":
            return self._greeting(job, meta, event)
        if event.to_state == "resume_sent":
            return self._resume(job, meta, event)
        if (
            event.to_state in {"initial_contact", "resume_requested", "interview_pending"}
            or event.reason_code == "employer_rejected"
        ):
            return self._inbound(
                job,
                meta,
                conversation_id=event.conversation_id,
                inbound_event_id=event.inbound_event_id,
                reference=event.evidence_reference,
                kind=event.evidence_kind,
                observed_at=event.changed_at,
            )
        base = dict(
            reference=event.evidence_reference,
            kind=event.evidence_kind,
            observed_at=event.changed_at,
            source_at=event.changed_at,
        )
        if event.to_state == "greeting_read":
            return self._read(job, meta, event)
        if event.to_state == "interviewed" or event.reason_code == "user_abandoned":
            if (
                event.evidence_kind != "owner_message"
                or not event.owner_text
                or not event.owner_text.strip()
            ):
                reject("Completion or abandonment needs the owner's actual reply reference.")
            return PipelineVerifiedEvidence.model_validate(
                {
                    **base,
                    "interview_completed": event.to_state == "interviewed",
                    "owner_decision": True,
                }
            )
        if event.reason_code == "job_closed":
            if (
                event.evidence_kind not in {"detail_page", "list_status"}
                or event.job_url != job.job_url
            ):
                reject("Job closure needs an actual detail/list capture for this exact URL.")
            return PipelineVerifiedEvidence.model_validate({**base, "job_closed": True})
        if event.reason_code in {"read_no_reply_2d", "no_reply_2d"}:
            if event.evidence_kind not in {"conversation_message", "list_message"}:
                reject("No reply requires a loaded conversation observation.")
            return PipelineVerifiedEvidence.model_validate(base)
        reject("No supported evidence adapter exists for this transition.")

    def _greeting(
        self, job: PipelineJob, meta: PipelineMeta, event: PipelineTransition
    ) -> PipelineVerifiedEvidence:
        if meta.recontact_approval_event_id:
            from jobagent.storage.pipeline_recontact import PipelineRecontactService

            return PipelineRecontactService(self.database).greeting_proof(job, meta, event)
        if (
            event.evidence_kind != "send_audit"
            or not event.send_reference
            or event.send_reference != event.evidence_reference
            or event.readback_text is None
        ):
            reject("Greeting transition needs the original sent audit and exact readback.")
        store = SqliteOutreachRepository(self.database)
        audit = next((a for a in store.list_audits() if a.audit_id == event.send_reference), None)
        if audit is None:
            reject("Existing greeting sent audit was not found.")
        batch, approval = store.get_batch(audit.batch_id), store.get_approval(audit.batch_id)
        if batch is None or approval is None:
            reject("Greeting send has no existing batch and bound human approval.")
        proof = outreach_proof(batch, approval, audit, event.readback_text)
        if (
            proof.job_id != meta.normalized_job_id
            or proof.job_url != job.job_url
            or proof.platform != job.platform
            or proof.sent_at > event.changed_at
            or event.readback_text != job.draft_greeting
            or proof.sent_text_hash != job.draft_digest
            or (meta.contact_round > 1 and proof.sent_at < job.entered_at)
        ):
            reject("Approved greeting, target, contact round and exact draft must all match.")
        return PipelineVerifiedEvidence(
            reference=event.evidence_reference,
            kind=event.evidence_kind,
            observed_at=event.changed_at,
            source_at=proof.sent_at,
            sent_text=event.readback_text,
            greeting_version=batch.harness_version,
            sent_at=proof.sent_at,
            send_reference=proof.send_reference,
        )

    def _resume(
        self, job: PipelineJob, meta: PipelineMeta, event: PipelineTransition
    ) -> PipelineVerifiedEvidence:
        if (
            event.evidence_kind != "send_audit"
            or not event.send_reference
            or event.send_reference != event.evidence_reference
            or event.readback_text is None
        ):
            reject("Resume transition needs its successful approved reply and exact readback.")
        conversation, events = self._conversation(job, meta, event.conversation_id)
        proof = reply_proof(
            conversation, events, event.send_reference, event.readback_text, str(job.job_url)
        )
        result = next(e for e in events if e.event_id == event.send_reference)
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
        if approval is None or approval.reply is None or approval.reply.kind != ReplyKind.RESUME:
            reject("A text reply cannot stand in for a custom resume attachment send.")
        attached = next(
            (
                e
                for e in reversed(events)
                if e.kind == EventKind.RESUME_ATTACHED and e.seq < approval.seq
            ),
            None,
        )
        ask = self.conversations.get_ask(approval.ask_id or "")
        if (
            attached is None
            or ask is None
            or ask.subject != "reply"
            or ask.conversation_id != conversation.conversation_id
            or ask.reply_digest != approval.reply_digest
            or ask.reply != approval.reply
            or not attached.seq <= ask.anchor_seq < approval.seq
            or attached.recorded_at.tzinfo is None
            or ask.asked_at.tzinfo is None
            or attached.recorded_at > ask.asked_at
            or not ask.asked_at <= approval.recorded_at <= result.recorded_at
            or any(
                e.kind in {EventKind.RESUME_ATTACHED, EventKind.INBOUND}
                and approval.seq < e.seq < result.seq
                for e in events
            )
        ):
            reject("Resume attachment or approval changed before the actual sent result.")
        assert attached is not None
        if (
            not attached.resume_variant_id
            or not attached.pdf_digest
            or event.resume_version != attached.resume_variant_id
            or event.resume_file_id != attached.pdf_digest
            or event.attachment_digest != attached.pdf_digest
            or job.sent_at is None
            or not job.sent_at <= proof.sent_at <= event.changed_at
            or proof.job_id != meta.normalized_job_id
            or proof.platform != job.platform
        ):
            reject("Resume send must bind the verified custom variant and exact PDF content ID.")
        return PipelineVerifiedEvidence(
            reference=event.evidence_reference,
            kind=event.evidence_kind,
            observed_at=event.changed_at,
            source_at=proof.sent_at,
            sent_at=proof.sent_at,
            send_reference=proof.send_reference,
            resume_version=attached.resume_variant_id,
            resume_file_id=attached.pdf_digest,
        )

    def _read(
        self, job: PipelineJob, meta: PipelineMeta, event: PipelineTransition
    ) -> PipelineVerifiedEvidence:
        if (
            event.evidence_kind not in {"conversation_message", "list_message"}
            or job.sent_at is None
        ):
            reject("Read state cannot be inferred from counters or unverified sends.")
        source_at = event.changed_at
        if event.conversation_id is not None:
            conversation, _ = self._conversation(job, meta, event.conversation_id)
            receipt = next(
                (
                    r
                    for r in self.conversations.receipts()
                    if r.conversation_id == conversation.conversation_id
                    and r.status == "read"
                    and r.snapshot_id == event.evidence_reference
                    and r.observed_at.tzinfo is not None
                    and job.sent_at <= r.observed_at <= event.changed_at
                ),
                None,
            )
            if receipt is not None:
                source_at = receipt.observed_at
            elif event.job_url != job.job_url:
                reject("Read evidence requires its stored receipt or matching private capture URL.")
        elif event.job_url != job.job_url:
            reject("Host-attested read capture must carry this exact target URL.")
        # The host remains responsible for actually viewing the receipt/capture.
        return PipelineVerifiedEvidence(
            reference=event.evidence_reference,
            kind=event.evidence_kind,
            observed_at=event.changed_at,
            source_at=source_at,
            read_confirmed=True,
        )
