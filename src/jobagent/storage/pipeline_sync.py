"""Refresh only real intake artifacts, preserving sent proof and immutable pipeline history."""

from datetime import datetime

from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.pipeline import context
from jobagent.outreach.service import _item_digest
from jobagent.schemas.jd_snapshot import JDSnapshot
from jobagent.schemas.job_intake import IntakeRecord
from jobagent.schemas.lexicon import JDFeatureSet
from jobagent.schemas.pipeline import PipelineArtifactBinding, PipelineJob, PipelineMeta
from jobagent.schemas.pipeline_sync import PipelineSyncRequest
from jobagent.storage.database import Database
from jobagent.storage.job_intake_service import JobIntakeService
from jobagent.storage.pipeline_repository import Pair, PipelineRepository
from jobagent.storage.pipeline_service import salary_fields


class PipelineSyncService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = PipelineRepository(database)
        self.intake = JobIntakeService(database)

    def source(self, job: PipelineJob, meta: PipelineMeta) -> IntakeRecord:
        provider_id = meta.source_job_id
        if provider_id is None and meta.normalized_job_id is not None:
            existing = self.intake.jobs.get_job(meta.normalized_job_id)
            provider_id = existing.source_job_id if existing else None
        if provider_id is None:
            reject("Artifact sync needs the verified provider identity, not a title match.")
        if meta.intake_id:
            source = self.intake.repository.get(meta.intake_id, job.candidate_id)
            visited = set()
            while source.merged_into:
                if source.intake_id in visited:
                    reject("Intake identity lineage contains a cycle.")
                visited.add(source.intake_id)
                source = self.intake.repository.get(source.merged_into, job.candidate_id)
        else:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT state_json FROM job_intakes WHERE candidate_id = ?", (job.candidate_id,)
                ).fetchall()
            matches = [IntakeRecord.model_validate_json(row[0]) for row in rows]
            matches = [
                row
                for row in matches
                if not row.merged_into
                and not row.closed
                and row.platform == job.platform
                and row.job_url == job.job_url
                and row.source_job_id == provider_id
                and (meta.domain is None or row.domain == meta.domain)
            ]
            if len(matches) != 1:
                reject("Artifact sync requires one exact private intake binding.")
            source = matches[0]
        if (
            source.candidate_id != job.candidate_id
            or source.platform != job.platform
            or source.job_url != job.job_url
            or source.source_job_id != provider_id
            or (meta.domain is not None and source.domain != meta.domain)
        ):
            reject("Intake artifacts belong to a different candidate, domain or provider target.")
        return source

    def artifacts(
        self, job: PipelineJob, meta: PipelineMeta, *, now: datetime
    ) -> tuple[IntakeRecord, dict[str, object], dict[str, object], str]:
        row = self.source(job, meta)
        if row.updated_at > now:
            reject("Intake evidence cannot come from the future.")
        cached = self.intake.jobs.get_job(row.job_id) if row.job_id else None
        if cached and (
            cached.source != job.platform
            or cached.url != job.job_url
            or cached.source_job_id != row.source_job_id
            or (meta.normalized_job_id is not None and cached.id != meta.normalized_job_id)
        ):
            reject("Normalized job identity does not match the bound provider target.")
        history = self.intake.repository.history(row.intake_id, job.candidate_id)
        snapshots = self.intake.knowledge.list_snapshots(cached.id) if cached else []
        latest = snapshots[-1] if snapshots else None
        selected = self.intake.knowledge.get(row.snapshot_id) if row.snapshot_id else None
        snapshot: JDSnapshot | None = None
        if (
            not row.closed
            and cached is not None
            and selected is not None
            and latest is not None
            and latest.snapshot_id == selected.snapshot_id
            and selected.completeness == "full"
            and selected.job_id == cached.id
            and selected.job_url == job.job_url
            and selected.platform == job.platform
            and selected.fetched_at <= now
            and row.snapshot_version == selected.snapshot_version
            and row.jd_text_hash == selected.jd_text_hash
            and cached.jd_raw.strip() == selected.jd_text.strip()
            and any(
                event.kind == "snapshot"
                and event.state.snapshot_id == selected.snapshot_id
                and event.state.job_id == cached.id
                and event.state.jd_text_hash == selected.jd_text_hash
                and event.state.snapshot_version == selected.snapshot_version
                for event in history
            )
        ):
            snapshot = selected
        features: JDFeatureSet | None = None
        if snapshot is not None and row.feature_set_id:
            actual = self.intake.features(row.feature_set_id)
            if (
                actual.snapshot_id == snapshot.snapshot_id
                and actual.job_id == snapshot.job_id
                and actual.snapshot_version == snapshot.snapshot_version
                and actual.jd_text_hash == snapshot.jd_text_hash
                and any(
                    event.kind == "factorize"
                    and event.state.feature_set_id == row.feature_set_id
                    and event.state.snapshot_id == snapshot.snapshot_id
                    for event in history
                )
            ):
                features = actual
        draft = row.draft if snapshot else None
        bound_snapshot_id = snapshot.snapshot_id if snapshot else None
        if draft is not None and (
            cached is None
            or draft.job_id != cached.id
            or draft.platform != job.platform
            or not any(
                event.kind == "draft"
                and event.state.snapshot_id == bound_snapshot_id
                and event.state.draft is not None
                and event.state.draft_digest == row.draft_digest
                and text_digest(event.state.draft.text) == text_digest(draft.text)
                for event in history
            )
        ):
            draft = None
        batch = self.intake.outreach.get_batch(row.batch_id) if row.batch_id else None
        draft_hash = text_digest(draft.text) if draft else None
        version = "CONTENT_" + draft_hash[7:23] if draft_hash else None
        expected_item_digest = _item_digest(cached, draft) if cached and draft else None
        if (
            draft
            and batch
            and batch.harness_version
            and any(
                event.kind == "batch"
                and event.state.batch_id == row.batch_id
                and event.state.draft_digest == row.draft_digest
                and event.state.snapshot_id == bound_snapshot_id
                for event in history
            )
            and any(
                item.job_id == draft.job_id
                and item.platform == draft.platform
                and item.text == draft.text
                and item.item_digest == expected_item_digest
                for item in batch.items
            )
        ):
            version = batch.harness_version
        raw = (
            (snapshot.salary_raw or "")
            if snapshot
            else ((row.listing.salary_text or "") if row.listing else job.salary_raw)
        )
        low, high, verified = None, None, "review"
        if meta.salary_minimum_k is not None and meta.salary_currency is not None:
            low, high, verified = salary_fields(raw, meta.salary_currency, meta.salary_minimum_k)
        changes: dict[str, object] = {
            "jd_text": snapshot.jd_text if snapshot else None,
            "jd_text_hash": snapshot.jd_text_hash if snapshot else None,
            "draft_greeting": draft.text if draft else None,
            "draft_digest": draft_hash,
            "draft_version": version,
            "salary_raw": raw,
            "salary_min_k": low,
            "salary_max_k": high,
            "salary_verified": verified,
        }
        extra: dict[str, object] = {
            "intake_id": row.intake_id,
            "source_intake_version": row.version,
            "domain": row.domain,
            "normalized_job_id": cached.id if cached else meta.normalized_job_id,
            "source_job_id": row.source_job_id,
            "snapshot_id": snapshot.snapshot_id if snapshot else None,
            "feature_set_id": row.feature_set_id if features else None,
            "scenario": sorted(
                {
                    f.term
                    for f in features.features
                    if f.dimension == "scenario" and f.polarity == "positive"
                }
            )
            if features
            else [],
            "tech": sorted(
                {
                    f.term
                    for f in features.features
                    if f.dimension == "tech" and f.polarity == "positive"
                }
            )
            if features
            else [],
        }
        source_digest = canonical_digest(
            {
                "intake": row.model_dump(mode="json"),
                "history": [e.model_dump(mode="json") for e in history],
                "normalized_job": cached.model_dump(mode="json") if cached else None,
                "selected_snapshot": selected.model_dump(mode="json") if selected else None,
                "latest_snapshot": latest.model_dump(mode="json") if latest else None,
                "features": features.model_dump(mode="json") if features else None,
                "batch": batch.model_dump(mode="json") if batch else None,
                "salary_minimum_k": meta.salary_minimum_k,
                "salary_currency": meta.salary_currency,
            }
        )
        return row, changes, extra, source_digest

    def sync(self, data: dict[str, object], *, now: datetime) -> Pair:
        request = PipelineSyncRequest.model_validate(data)
        digest = canonical_digest(["sync", request.model_dump(mode="json")])
        with self.database.connect() as connection:
            old = self.repository.replay(connection, request.event_id, request.candidate_id, digest)
        if old:
            return old
        if now.tzinfo is None:
            reject("Artifact observations need a timezone-aware time.")
        job, meta = self.repository.get(request.pipeline_id, request.candidate_id)
        context(job, meta, request.candidate_id, request.expected_version, now, now)
        row, _changes, _extra, source_digest = self.artifacts(job, meta, now=now)
        evidence_reference = "INTAKE_" + row.intake_id
        event = PipelineArtifactBinding(
            event_id=request.event_id,
            pipeline_id=job.pipeline_id,
            candidate_id=job.candidate_id,
            expected_version=request.expected_version,
            observed_at=now,
            kind="artifact_sync",
            evidence_reference=evidence_reference,
            source_digest=source_digest,
        )

        def operation(
            current: PipelineJob, metadata: PipelineMeta
        ) -> tuple[PipelineJob, PipelineMeta, None]:
            context(current, metadata, request.candidate_id, request.expected_version, now, now)
            _row, changes, extra, actual_digest = self.artifacts(current, metadata, now=now)
            if actual_digest != source_digest:
                reject("Source artifacts changed during sync; reload the current bindings.")
            if metadata.recontact_approval_event_id:
                jd_changed = (
                    extra["snapshot_id"] != metadata.recontact_snapshot_id
                    or changes["jd_text_hash"] != metadata.recontact_jd_text_hash
                )
                if current.pipeline_state == "draft_pending" and jd_changed:
                    changes.update(draft_greeting=None, draft_digest=None, draft_version=None)
                    extra.update(
                        recontact_conversation_id=None,
                        recontact_approval_event_id=None,
                        recontact_reply_digest=None,
                        recontact_ask_id=None,
                        recontact_snapshot_id=None,
                        recontact_jd_text_hash=None,
                        paused=True,
                        pause_reason="recontact_jd_changed",
                    )
                else:
                    # This round consumes a real approved conversation reply, not the
                    # intake's previous first greeting. Sent facts remain immutable.
                    changes.update(
                        draft_greeting=current.draft_greeting,
                        draft_digest=current.draft_digest,
                        draft_version=current.draft_version,
                    )
            changed = PipelineJob.model_validate(
                {**current.model_dump(), **changes, "updated_at": now}
            )
            updated = PipelineMeta.model_validate(
                {
                    **metadata.model_dump(),
                    **extra,
                    "version": metadata.version + 1,
                    "last_evidence_reference": evidence_reference,
                }
            )
            return changed, updated, None

        return self.repository.mutate(event, now=now, input_digest=digest, operation=operation)
