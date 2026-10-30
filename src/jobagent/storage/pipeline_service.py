"""Read existing artifacts and compose pipeline operations without sending authority."""

import json
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.pipeline import (
    PipelineCreate,
    PipelineJob,
    PipelineMeta,
    PipelineObservation,
    PipelineTransition,
)
from jobagent.storage.database import Database
from jobagent.storage.job_intake_service import JobIntakeService
from jobagent.storage.pipeline_repository import Pair, PipelineRepository


def salary_fields(raw: str, currency: str, minimum_k: int) -> tuple[int | None, int | None, str]:
    parsed, _ = JobNormalizer(default_currency=currency)._parse_salary(raw)
    if parsed is None or parsed.currency != currency.upper() or parsed.period != "month":
        return None, None, "review"

    def thousands(value: Decimal | None) -> int | None:
        if value is None or value % 1000:
            return None
        return int(value / 1000)

    lower, upper = thousands(parsed.minimum), thousands(parsed.maximum)
    return lower, upper, "review" if upper is None else "pass" if upper >= minimum_k else "fail"


class PipelineService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = PipelineRepository(database)
        self.intake = JobIntakeService(database)

    def create(self, data: dict[str, object], *, now: datetime) -> Pair:
        request = PipelineCreate.model_validate(data)
        digest = canonical_digest(["create", request.model_dump(mode="json")])
        with self.database.connect() as connection:
            previous = self.repository.replay(
                connection, request.event_id, request.candidate_id, digest
            )
        if previous:
            return previous
        with self.database.connect() as connection:
            legacy = connection.execute(
                "SELECT 1 FROM sent_tracking_roots WHERE candidate_id = ? LIMIT 1",
                (request.candidate_id,),
            ).fetchone()
            active = connection.execute(
                "SELECT 1 FROM pipeline_authorities WHERE candidate_id = ?", (request.candidate_id,)
            ).fetchone()
        if legacy and not active:
            reject("Adopt existing tracking offline before activating a new pipeline authority.")
        intake = (
            self.intake.repository.get(request.intake_id, request.candidate_id)
            if request.intake_id
            else None
        )
        cached = self.intake.jobs.get_job(
            request.normalized_job_id or (intake.job_id if intake else "") or ""
        )
        listing = intake.listing if intake else None
        if cached is None and listing is None:
            reject("Pipeline creation needs an actual cached job or resolved intake listing.")
        platform = cached.source if cached else listing.source if listing else ""
        if platform not in {"boss", "zhaopin"}:
            reject("Pipeline supports only configured personal-AI boards.")
        source_id = cached.source_job_id if cached else listing.source_job_id if listing else ""
        url = cached.url if cached else listing.url if listing else None
        if url is None:
            reject("Unresolved references stay in intake; no placeholder pipeline job is created.")
        if intake and (
            intake.platform != platform
            or intake.job_url != url
            or intake.source_job_id != source_id
        ):
            reject("Pipeline source does not match the original intake identity.")
        if request.domain is not None and (intake is None or request.domain != intake.domain):
            reject("Domain must come from the bound private intake policy.")
        source_key = platform + "-" + source_id
        candidate_rows = self.repository.list_records(request.candidate_id)
        if any(
            old.platform == platform
            and old.job_url == url
            and metadata.source_job_id is not None
            and metadata.source_job_id != source_id
            for old, metadata in candidate_rows
        ):
            reject(
                "Stored URL has a different provider; resolve its identity before a new contact."
            )
        existing = [
            pair
            for pair in candidate_rows
            if pair[0].platform == platform
            and (
                pair[0].job_id == source_key
                or pair[1].source_job_id == source_id
                or (pair[0].job_url == url and pair[1].source_job_id is None)
            )
        ]
        if existing:
            source_key = max(
                existing, key=lambda pair: (pair[1].contact_round, pair[0].updated_at)
            )[0].job_id
        if any(job.pipeline_state != "abandoned" for job, _ in existing):
            reject("An active pipeline already owns this source job.")
        round_number = max((meta.contact_round for _, meta in existing), default=0) + 1
        if existing and not (
            request.recontact_owner_text
            and request.recontact_owner_text.strip()
            and request.recontact_owner_reference
        ):
            reject("Recontact needs a new explicit owner request and fresh approval/send evidence.")
        identity = "PIPE_" + canonical_digest([request.candidate_id, source_key])[7:23].upper()
        if round_number > 1:
            identity += "_R" + str(round_number)
        snapshot = None
        if cached:
            snapshots = self.intake.knowledge.list_snapshots(cached.id)
            if (
                snapshots
                and snapshots[-1].completeness == "full"
                and snapshots[-1].jd_text.strip() == cached.jd_raw.strip()
            ):
                snapshot = snapshots[-1]
        raw = (
            (snapshot.salary_raw if snapshot else None)
            or (listing.salary_text if listing else None)
            or ""
        )
        low, high, verified = salary_fields(raw, request.salary_currency, request.salary_minimum_k)
        draft = intake.draft if intake else None
        draft_hash = text_digest(draft.text) if draft else None
        job = PipelineJob.model_validate(
            dict(
                pipeline_id=identity,
                candidate_id=request.candidate_id,
                job_id=source_key,
                platform=platform,
                job_url=url,
                title=cached.title if cached else listing.title if listing else "",
                company=cached.company if cached else listing.company if listing else "",
                location=cached.location if cached else listing.location if listing else None,
                salary_raw=raw,
                salary_min_k=low,
                salary_max_k=high,
                salary_verified=verified,
                jd_text=snapshot.jd_text if snapshot else None,
                jd_text_hash=snapshot.jd_text_hash if snapshot else None,
                jd_points=json.dumps(request.jd_points, ensure_ascii=False)
                if request.jd_points
                else None,
                draft_greeting=draft.text if draft else None,
                draft_digest=draft_hash,
                draft_version="CONTENT_" + draft_hash[7:23] if draft_hash else None,
                pipeline_state="draft_pending",
                state_reason="normal",
                state_changed_at=now,
                entered_at=now,
                updated_at=now,
            )
        )
        feature_id = intake.feature_set_id if intake else None
        features = self.intake.features(feature_id) if feature_id else None
        if features and snapshot and features.snapshot_id != snapshot.snapshot_id:
            features = None
            feature_id = None
        meta = PipelineMeta(
            pipeline_id=identity,
            contact_round=round_number,
            normalized_job_id=cached.id if cached else None,
            source_job_id=source_id,
            intake_id=intake.intake_id if intake else None,
            domain=intake.domain if intake else None,
            salary_minimum_k=request.salary_minimum_k,
            salary_currency=request.salary_currency,
            snapshot_id=snapshot.snapshot_id if snapshot else None,
            feature_set_id=feature_id,
            entered_evidence_reference=request.recontact_owner_reference
            or request.evidence_reference,
            scenario=[
                f.term
                for f in features.features
                if f.dimension == "scenario" and f.polarity == "positive"
            ]
            if features
            else [],
            tech=[
                f.term
                for f in features.features
                if f.dimension == "tech" and f.polarity == "positive"
            ]
            if features
            else [],
        )
        return self.repository.create(
            job,
            meta,
            event_id=request.event_id,
            evidence_reference=request.recontact_owner_reference or request.evidence_reference,
            input_digest=digest,
        )

    def transition(self, data: dict[str, object], *, now: datetime) -> Pair:
        try:
            event = PipelineTransition.model_validate(data)
        except ValidationError as error:
            self.repository.rejection(data, now=now, code="invalid_contract")
            raise ContractValidationError("Pipeline transition contract is invalid.") from error
        from jobagent.storage.pipeline_proofs import PipelineProofResolver

        with self.database.connect() as connection:
            old = self.repository.replay(
                connection,
                event.event_id,
                event.candidate_id,
                canonical_digest(event.model_dump(mode="json")),
            )
        if old:
            return old
        job, meta = self.repository.get(event.pipeline_id, event.candidate_id)
        try:
            proof = PipelineProofResolver(self.database).resolve(job, meta, event, now=now)
            return self.repository.transition(event, proof, now=now)
        except ContractValidationError as error:
            self.repository.rejection(data, now=now, code="evidence_rejected")
            if error.details.get(
                "reason"
            ) == "readback_mismatch" and self._matching_transition_send(job, meta, event, now=now):
                self._pause_readback_fault(
                    job,
                    meta,
                    event_id=event.event_id,
                    send_reference=event.send_reference or event.evidence_reference,
                    expected_version=event.expected_version,
                    now=now,
                )
            raise

    def _matching_outreach_send(
        self, job: PipelineJob, normalized_job_id: str | None, reference: str, *, now: datetime
    ) -> bool:
        """Authenticate the stored audit with its own approved text, solely to scope a pause."""
        from jobagent.jobs.sent_tracking import outreach_proof
        from jobagent.storage.outreach_repository import SqliteOutreachRepository

        if normalized_job_id is None:
            return False
        store = SqliteOutreachRepository(self.database)
        audit = next((value for value in store.list_audits() if value.audit_id == reference), None)
        if audit is None:
            return False
        batch, approval = store.get_batch(audit.batch_id), store.get_approval(audit.batch_id)
        if batch is None or approval is None:
            return False
        item = next((value for value in batch.items if value.number == audit.number), None)
        if item is None:
            return False
        try:
            proof = outreach_proof(batch, approval, audit, item.text)
        except ContractValidationError:
            return False
        return (
            proof.job_id == normalized_job_id
            and proof.platform == job.platform
            and proof.job_url == job.job_url
            and job.entered_at <= proof.sent_at <= now
        )

    def _matching_transition_send(
        self, job: PipelineJob, meta: PipelineMeta, event: PipelineTransition, *, now: datetime
    ) -> bool:
        """A readback fault is actionable only after the original target/proof is authenticated."""
        if not event.send_reference or event.send_reference != event.evidence_reference:
            return False
        if event.to_state == "greeting_sent":
            if meta.recontact_approval_event_id:
                from jobagent.storage.pipeline_recontact import PipelineRecontactService

                if job.draft_greeting is None:
                    return False
                original = event.model_copy(update={"readback_text": job.draft_greeting})
                try:
                    # Authenticate the original target/source only; never save a repaired readback.
                    PipelineRecontactService(self.database).greeting_proof(job, meta, original)
                except ContractValidationError:
                    return False
                return True
            return self._matching_outreach_send(
                job, meta.normalized_job_id, event.send_reference, now=now
            )
        if event.to_state != "resume_sent":
            return False
        from jobagent.schemas.conversation import EventKind
        from jobagent.storage.conversation_repository import SqliteConversationRepository
        from jobagent.storage.pipeline_proofs import PipelineProofResolver

        store = SqliteConversationRepository(self.database)
        conversation = store.get_conversation(event.conversation_id or "")
        if conversation is None:
            return False
        events = store.list_events(conversation.conversation_id)
        result = next((value for value in events if value.event_id == event.send_reference), None)
        if result is None:
            return False
        approval = next(
            (
                value
                for value in reversed(events)
                if value.kind == EventKind.REPLY_APPROVED
                and value.seq < result.seq
                and value.reply_digest == result.reply_digest
            ),
            None,
        )
        if approval is None or approval.reply is None:
            return False
        attached = next(
            (
                value
                for value in reversed(events)
                if value.kind == EventKind.RESUME_ATTACHED and value.seq < approval.seq
            ),
            None,
        )
        if attached is None:
            return False
        # This reconstructs only the authoritative proof for validation. It never records
        # repaired readback text or promotes the failed caller's transition.
        original = event.model_copy(
            update={
                "readback_text": approval.reply.text,
                "resume_version": attached.resume_variant_id,
                "resume_file_id": attached.pdf_digest,
                "attachment_digest": attached.pdf_digest,
            }
        )
        try:
            PipelineProofResolver(self.database).resolve(job, meta, original, now=now)
        except ContractValidationError:
            return False
        return True

    def _pause_readback_fault(
        self,
        job: PipelineJob,
        meta: PipelineMeta,
        *,
        event_id: str,
        send_reference: str,
        expected_version: int,
        now: datetime,
    ) -> None:
        stable_id = (
            "READBACK_MISMATCH_"
            + canonical_digest(
                [
                    job.candidate_id,
                    job.pipeline_id,
                    event_id,
                    send_reference,
                ]
            )[7:]
        )
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM pipeline_requests "
                "WHERE event_id = ? AND candidate_id = ? AND pipeline_id = ?",
                (stable_id, job.candidate_id, job.pipeline_id),
            ).fetchone()
            used = connection.execute(
                "SELECT pipeline_id FROM pipeline_used_sends WHERE send_reference = ?",
                (send_reference,),
            ).fetchone()
        if existing or (used is not None and used[0] != job.pipeline_id):
            return
        current, metadata = self.repository.get(job.pipeline_id, job.candidate_id)
        if (
            metadata.version != expected_version
            or metadata.version != meta.version
            or current.pipeline_state != job.pipeline_state
            or current.pipeline_state == "abandoned"
            or metadata.paused
            or now < current.updated_at
        ):
            return
        self.repository.observe(
            PipelineObservation(
                event_id=stable_id,
                pipeline_id=current.pipeline_id,
                candidate_id=current.candidate_id,
                expected_version=metadata.version,
                observed_at=now,
                kind="pause",
                evidence_kind="send_audit",
                evidence_reference=send_reference,
            ),
            now=now,
        )

    def observe(self, data: dict[str, object], *, now: datetime) -> Pair:
        try:
            event = PipelineObservation.model_validate(data)
        except ValidationError as error:
            self.repository.rejection(data, now=now, code="invalid_contract")
            raise ContractValidationError("Pipeline observation contract is invalid.") from error
        from jobagent.storage.pipeline_proofs import PipelineProofResolver

        job, meta = self.repository.get(event.pipeline_id, event.candidate_id)
        proof = (
            PipelineProofResolver(self.database).inbound(job, meta, event, now=now)
            if event.kind == "substantive_reply"
            else None
        )
        return self.repository.observe(event, now=now, proof=proof)

    def bind_send(self, data: dict[str, object], *, now: datetime) -> Pair:
        from jobagent.jobs.pipeline import context
        from jobagent.jobs.sent_tracking import outreach_proof
        from jobagent.schemas.pipeline import PipelineArtifactBinding, PipelineBindSend
        from jobagent.storage.outreach_repository import SqliteOutreachRepository

        request = PipelineBindSend.model_validate(data)
        digest = canonical_digest(["bind-send", request.model_dump(mode="json")])
        with self.database.connect() as connection:
            old = self.repository.replay(connection, request.event_id, request.candidate_id, digest)
        if old:
            return old
        job, meta = self.repository.get(request.pipeline_id, request.candidate_id)
        cached = self.intake.jobs.get_job(request.normalized_job_id)
        if (
            cached is None
            or cached.source != job.platform
            or cached.url != job.job_url
            or (meta.source_job_id is not None and cached.source_job_id != meta.source_job_id)
        ):
            reject("Legacy proof must resolve the original exact provider identity and URL.")
        store = SqliteOutreachRepository(self.database)
        audit = next((a for a in store.list_audits() if a.audit_id == request.audit_id), None)
        if audit is None:
            reject("An existing successful send audit is required.")
        batch, approval = store.get_batch(audit.batch_id), store.get_approval(audit.batch_id)
        if batch is None or approval is None:
            reject("Original batch and human approval must still be available.")
        try:
            proof = outreach_proof(batch, approval, audit, request.readback_text)
        except ContractValidationError as error:
            self.repository.rejection(data, now=now, code="send_proof_rejected")
            if error.details.get("reason") == "readback_mismatch" and self._matching_outreach_send(
                job, cached.id, request.audit_id, now=now
            ):
                self._pause_readback_fault(
                    job,
                    meta,
                    event_id=request.event_id,
                    send_reference=request.audit_id,
                    expected_version=request.expected_version,
                    now=now,
                )
            raise
        if (
            proof.job_id != cached.id
            or proof.job_url != job.job_url
            or proof.platform != job.platform
            or not job.entered_at <= proof.sent_at <= now
        ):
            reject("Send proof or entry time does not match this historical contact.")
        event = PipelineArtifactBinding(
            event_id=request.event_id,
            pipeline_id=job.pipeline_id,
            candidate_id=request.candidate_id,
            expected_version=request.expected_version,
            observed_at=now,
            kind="send_proof_bound",
            evidence_reference=request.audit_id,
            send_reference=proof.send_reference,
            source_digest=canonical_digest(proof.model_dump(mode="json")),
        )

        def operation(
            current: PipelineJob, metadata: PipelineMeta
        ) -> tuple[PipelineJob, PipelineMeta, None]:
            context(current, metadata, request.candidate_id, request.expected_version, now, now)
            if (
                current.pipeline_state != "greeting_sent"
                or metadata.proof_status != "proof_pending"
            ):
                reject("Only an unverified historical send declaration can bind this proof.")
            updated = PipelineJob.model_validate(
                {
                    **current.model_dump(),
                    "sent_greeting": request.readback_text,
                    "sent_text_hash": proof.sent_text_hash,
                    "sent_at": proof.sent_at,
                    "send_readback": "exact",
                    "updated_at": now,
                }
            )
            revised = metadata.model_copy(
                update={
                    "version": metadata.version + 1,
                    "proof_status": "verified",
                    "normalized_job_id": cached.id,
                    "source_job_id": cached.source_job_id,
                    "last_evidence_reference": request.audit_id,
                    "sent_greeting_version": batch.harness_version,
                }
            )
            return updated, revised, None

        return self.repository.mutate(event, now=now, input_digest=digest, operation=operation)
