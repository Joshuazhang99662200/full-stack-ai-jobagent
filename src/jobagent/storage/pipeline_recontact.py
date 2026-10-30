"""Record existing approved recontact replies; never issue approval, lease or send.

Conversation records have no candidate identity. Isolation here is the candidate-owned
pipeline's exact normalized provider job/URL within the same private database.
"""

from datetime import datetime

from jobagent.conversation.service import ConversationService
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.pipeline import context
from jobagent.jobs.sent_tracking import reply_proof
from jobagent.schemas.conversation import (
    TERMINAL_STAGES,
    Conversation,
    ConversationAsk,
    ConversationEvent,
    EventKind,
    ReplyKind,
    ReplyResult,
)
from jobagent.schemas.pipeline import (
    PipelineArtifactBinding,
    PipelineJob,
    PipelineMeta,
    PipelineTransition,
    PipelineVerifiedEvidence,
)
from jobagent.schemas.pipeline_recontact import PipelineBindReplyInput
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.pipeline_repository import Pair, PipelineRepository


class PipelineRecontactService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = PipelineRepository(database)
        self.conversations = SqliteConversationRepository(database)

    def approved_reply(
        self,
        job: PipelineJob,
        meta: PipelineMeta,
        conversation_id: str,
        approval_id: str,
        *,
        now: datetime,
        result_event_id: str | None = None,
    ) -> tuple[Conversation, list[ConversationEvent], ConversationAsk, ConversationEvent, str]:
        """Read and validate original ask/approval, with the original conversation rules."""
        if meta.contact_round <= 1 or not meta.normalized_job_id or now.tzinfo is None:
            reject("Only an explicitly requested later contact round may bind an existing reply.")
        cached = SqliteJobRepository(self.database).get_job(meta.normalized_job_id)
        conversation = self.conversations.get_conversation(conversation_id)
        if (
            cached is None
            or cached.source != job.platform
            or cached.url != job.job_url
            or (meta.source_job_id is not None and cached.source_job_id != meta.source_job_id)
            or conversation is None
            or conversation.job_id != cached.id
            or conversation.platform != job.platform
        ):
            reject("Reply evidence must bind this pipeline's exact resolved provider job and URL.")
        events = self.conversations.list_events(conversation_id)
        core = ConversationService()
        if core.stage(events) is None or core.stage(events) in TERMINAL_STAGES:
            reject("A closed or declined conversation cannot be reopened by pipeline binding.")
        approval = next((e for e in events if e.event_id == approval_id), None)
        if (
            approval is None
            or approval.kind != EventKind.REPLY_APPROVED
            or approval.reply is None
            or approval.reply.kind not in {ReplyKind.FOLLOW_UP, ReplyKind.ANSWER}
            or not approval.attestation
            or not approval.attestation.strip()
            or not approval.ask_id
            or approval.recorded_at.tzinfo is None
            or not job.entered_at <= approval.recorded_at <= now
        ):
            reject("Recontact requires a fresh existing human-approved follow-up or answer.")
        ask = self.conversations.get_ask(approval.ask_id)
        before = [e for e in events if e.seq < approval.seq]
        if (
            ask is None
            or ask.subject != "reply"
            or ask.conversation_id != conversation_id
            or ask.reply != approval.reply
            or ask.reply_digest != approval.reply_digest
            or ask.harness_version != approval.harness_version
            or ask.original_reply_digest != approval.original_reply_digest
            or not before
            or ask.anchor_seq != before[-1].seq
            or approval.seq != ask.anchor_seq + 1
            or ask.asked_at.tzinfo is None
            or before[-1].recorded_at.tzinfo is None
            or not job.entered_at <= ask.asked_at <= approval.recorded_at
            or before[-1].recorded_at > ask.asked_at
            or any(e.recorded_at.tzinfo is None or e.recorded_at > now for e in events)
            or any(
                e.inbound is not None
                and (e.inbound.received_at.tzinfo is None or e.inbound.received_at > ask.asked_at)
                for e in before
            )
        ):
            reject("Existing reply approval must retain its exact stored ask and unchanged anchor.")
        # Pure validation creates no persisted question or approval and authorizes no send.
        checked = core.draft_reply(
            conversation,
            before,
            approval.reply,
            now=ask.asked_at,
            harness_version=ask.harness_version,
        )
        if checked.ask_id != ask.ask_id or checked.reply_digest != approval.reply_digest:
            reject("Reply digest does not match its original conversation and question.")
        boundary = None
        if result_event_id is not None:
            boundary = next((e for e in events if e.event_id == result_event_id), None)
            if (
                boundary is None
                or boundary.kind != EventKind.REPLY_RESULT
                or boundary.result != ReplyResult.SENT
                or boundary.reply_digest != approval.reply_digest
                or boundary.seq <= approval.seq
                or boundary.recorded_at < approval.recorded_at
            ):
                reject("Recontact requires the successful result of this exact bound approval.")
        later = [
            e for e in events if e.seq > approval.seq and (boundary is None or e.seq < boundary.seq)
        ]
        if any(
            e.kind
            in {
                EventKind.INBOUND,
                EventKind.RESUME_ATTACHED,
                EventKind.REPLY_APPROVED,
                EventKind.REPLY_RESULT,
            }
            for e in later
        ):
            reject("The reply question or approval changed before its actual result.")
        if boundary is None and core._pending_approval(events) != approval:
            reject("The original reply is no longer pending; binding creates no new approval.")
        snapshots = SqliteJDSnapshotRepository(self.database).list_snapshots(cached.id)
        if snapshots and snapshots[-1].fetched_at > ask.asked_at:
            reject("The JD source changed after this question; fresh owner approval is required.")
        if (job.jd_text_hash is not None or meta.snapshot_id is not None) and (
            not snapshots
            or snapshots[-1].snapshot_id != meta.snapshot_id
            or snapshots[-1].jd_text_hash != job.jd_text_hash
            or snapshots[-1].fetched_at > now
            or job.jd_text is None
            or cached.jd_raw.strip() != job.jd_text.strip()
        ):
            reject("JD source changed; synchronize and ask the owner for a fresh reply approval.")
        source_digest = canonical_digest(
            {
                "candidate_id": job.candidate_id,
                "pipeline_id": job.pipeline_id,
                "job": cached.model_dump(mode="json"),
                "snapshot_id": meta.snapshot_id,
                "jd_text_hash": job.jd_text_hash,
                "conversation": conversation.model_dump(mode="json"),
                "ask": ask.model_dump(mode="json"),
                "approval": approval.model_dump(mode="json"),
            }
        )
        return conversation, events, ask, approval, source_digest

    def bind_reply(self, data: dict[str, object], *, now: datetime) -> Pair:
        request = PipelineBindReplyInput.model_validate(data)
        digest = canonical_digest(["bind-reply", request.model_dump(mode="json")])
        with self.database.connect() as connection:
            old = self.repository.replay(connection, request.event_id, request.candidate_id, digest)
        if old:
            return old
        job, meta = self.repository.get(request.pipeline_id, request.candidate_id)
        context(job, meta, request.candidate_id, request.expected_version, now, now)
        if job.pipeline_state != "draft_pending":
            reject("Only a later contact round still awaiting its first send can bind a reply.")
        _, _, _, approval, source = self.approved_reply(
            job,
            meta,
            request.conversation_id,
            request.approval_event_id,
            now=now,
        )
        event = PipelineArtifactBinding(
            event_id=request.event_id,
            candidate_id=request.candidate_id,
            pipeline_id=request.pipeline_id,
            expected_version=request.expected_version,
            observed_at=now,
            kind="artifact_sync",
            evidence_reference=approval.event_id,
            source_digest=source,
        )

        def operation(
            current: PipelineJob, metadata: PipelineMeta
        ) -> tuple[PipelineJob, PipelineMeta, None]:
            context(current, metadata, request.candidate_id, request.expected_version, now, now)
            if current.pipeline_state != "draft_pending":
                reject("Recontact reply binding cannot alter an already-sent or terminal round.")
            _, _, original_ask, original, actual_source = self.approved_reply(
                current,
                metadata,
                request.conversation_id,
                request.approval_event_id,
                now=now,
            )
            if actual_source != source:
                reject("Reply evidence changed during binding; reload the original approval.")
            assert original.reply is not None
            text_hash = text_digest(original.reply.text)
            updated = PipelineJob.model_validate(
                {
                    **current.model_dump(),
                    "draft_greeting": original.reply.text,
                    "draft_digest": text_hash,
                    "draft_version": original.harness_version or "CONTENT_" + text_hash[7:23],
                    "updated_at": now,
                }
            )
            revised = PipelineMeta.model_validate(
                {
                    **metadata.model_dump(),
                    "version": metadata.version + 1,
                    "recontact_conversation_id": request.conversation_id,
                    "recontact_approval_event_id": original.event_id,
                    "recontact_reply_digest": original.reply_digest,
                    "recontact_ask_id": original_ask.ask_id,
                    "recontact_snapshot_id": metadata.snapshot_id,
                    "recontact_jd_text_hash": current.jd_text_hash,
                    "last_evidence_reference": original.event_id,
                }
            )
            return updated, revised, None

        return self.repository.mutate(event, now=now, input_digest=digest, operation=operation)

    def greeting_proof(
        self,
        job: PipelineJob,
        meta: PipelineMeta,
        event: PipelineTransition,
    ) -> PipelineVerifiedEvidence:
        if (
            not meta.recontact_approval_event_id
            or not meta.recontact_conversation_id
            or event.conversation_id != meta.recontact_conversation_id
            or not event.send_reference
            or event.readback_text is None
            or event.send_reference != event.evidence_reference
            or event.evidence_kind != "send_audit"
            or meta.recontact_snapshot_id != meta.snapshot_id
            or meta.recontact_jd_text_hash != job.jd_text_hash
        ):
            reject("An existing reply result must match this later round's exact bound approval.")
        conversation, events, ask, approval, _ = self.approved_reply(
            job,
            meta,
            meta.recontact_conversation_id,
            meta.recontact_approval_event_id,
            now=event.changed_at,
            result_event_id=event.send_reference,
        )
        assert approval.reply is not None
        if (
            meta.recontact_reply_digest != approval.reply_digest
            or meta.recontact_ask_id != ask.ask_id
            or job.draft_greeting != approval.reply.text
            or job.draft_digest != text_digest(approval.reply.text)
            or job.draft_version
            != (approval.harness_version or "CONTENT_" + job.draft_digest[7:23])
        ):
            reject("The current recontact draft differs from its exact original approval.")
        proof = reply_proof(
            conversation, events, event.send_reference, event.readback_text, str(job.job_url)
        )
        if not job.entered_at <= proof.sent_at <= event.changed_at:
            reject("A previous round's reply cannot prove a new contact.")
        return PipelineVerifiedEvidence(
            reference=event.evidence_reference,
            kind="send_audit",
            observed_at=event.changed_at,
            source_at=proof.sent_at,
            sent_at=proof.sent_at,
            send_reference=proof.send_reference,
            sent_text=event.readback_text,
            greeting_version=approval.harness_version,
        )
