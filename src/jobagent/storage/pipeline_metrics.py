"""Append-only pipeline analytics assembled from persistent state and source artifacts."""

import json
import sqlite3
from datetime import datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.pipeline_diagnosis import diagnose
from jobagent.jobs.pipeline_metrics import compute_metrics, salary_band
from jobagent.schemas.common import ContractModel
from jobagent.schemas.jd_snapshot import JDSnapshot
from jobagent.schemas.job_intake import IntakeRecord
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.lexicon import JDFeatureSet
from jobagent.schemas.outreach import OutreachBatch
from jobagent.schemas.pipeline import PipelineHistory, PipelineJob, PipelineMeta
from jobagent.schemas.pipeline_metrics import (
    ConfirmedPipelineMetricRule,
    ExclusionReason,
    PipelineDiagnosis,
    PipelineDiagnosisRequest,
    PipelineMetricEvidence,
    PipelineMetricFact,
    PipelineMetricRequest,
    PipelineMetricsComputeInput,
    PipelineStageMetric,
    PipelineStoredDiagnosisInput,
)
from jobagent.storage.database import Database
from jobagent.storage.pipeline_policy import require_pipeline_policy
from jobagent.storage.pipeline_repository import PipelineRepository


class PipelineMetricsService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = PipelineRepository(database)

    @staticmethod
    def _frozen(
        connection: sqlite3.Connection, job: PipelineJob, meta: PipelineMeta
    ) -> tuple[PipelineJob, PipelineMeta]:
        if meta.proof_status == "verified":
            for saved in connection.execute(
                "SELECT response_json FROM pipeline_requests WHERE pipeline_id = ? ORDER BY rowid",
                (job.pipeline_id,),
            ):
                value = json.loads(saved[0])
                old_job = PipelineJob.model_validate(value["job"])
                old_meta = PipelineMeta.model_validate(value["meta"])
                if old_meta.proof_status == "verified" and old_job.sent_at is not None:
                    return old_job, old_meta
        return job, meta

    @staticmethod
    def _features(
        connection: sqlite3.Connection, job: PipelineJob, meta: PipelineMeta
    ) -> tuple[str | None, list[str | None], list[str | None], list[str]]:
        references = [meta.entered_evidence_reference]
        domain = None
        if meta.intake_id is not None:
            saved = connection.execute(
                "SELECT state_json FROM job_intakes WHERE intake_id = ? AND candidate_id = ?",
                (meta.intake_id, job.candidate_id),
            ).fetchone()
            if saved is None:
                reject("Metric domain must bind an existing candidate intake policy.")
            intake = IntakeRecord.model_validate_json(saved[0])
            if intake.domain != meta.domain or intake.platform != job.platform:
                reject("Metric policy scope differs from its original intake provenance.")
            domain = intake.domain
            references.append(meta.intake_id)
        elif meta.domain is not None:
            reject("A metric domain cannot be supplied without its persistent policy source.")
        if meta.normalized_job_id is not None:
            saved_job = connection.execute(
                "SELECT job_json FROM normalized_jobs WHERE job_id = ?", (meta.normalized_job_id,)
            ).fetchone()
            if saved_job is None:
                reject("Metric job identity is missing its original normalized source.")
            normalized = NormalizedJob.model_validate_json(saved_job[0])
            if (
                normalized.source != job.platform
                or normalized.url != job.job_url
                or job.job_id != job.platform + "-" + normalized.source_job_id
            ):
                reject("Metric identity differs from the stored source job.")
        if meta.feature_set_id is None:
            if meta.scenario or meta.tech:
                reject("Metric feature tags require their stored source feature set.")
            return domain, [None], [None], references
        saved_feature = connection.execute(
            "SELECT feature_json FROM jd_feature_sets WHERE feature_set_id = ?",
            (meta.feature_set_id,),
        ).fetchone()
        saved_snapshot = connection.execute(
            "SELECT snapshot_json FROM jd_snapshots WHERE snapshot_id = ?", (meta.snapshot_id,)
        ).fetchone()
        if saved_feature is None or saved_snapshot is None:
            reject(
                "Metric features require the original full snapshot and persisted factorization."
            )
        features = JDFeatureSet.model_validate_json(saved_feature[0])
        snapshot = JDSnapshot.model_validate_json(saved_snapshot[0])
        if (
            features.snapshot_id != snapshot.snapshot_id
            or features.job_id != meta.normalized_job_id
            or snapshot.job_id != meta.normalized_job_id
            or features.jd_text_hash != snapshot.jd_text_hash
            or snapshot.jd_text_hash != text_digest(snapshot.jd_text)
            or snapshot.platform != job.platform
            or snapshot.job_url != job.job_url
            or snapshot.completeness != "full"
            or features.completeness != "full"
            or snapshot.jd_text != job.jd_text
        ):
            reject("Metric feature lineage does not match this exact full JD and job.")
        for feature in features.features:
            if snapshot.jd_text[feature.start : feature.end] != feature.evidence:
                reject("A metric feature lacks its exact original JD evidence span.")
        scenarios = sorted(
            {
                f.term
                for f in features.features
                if f.dimension == "scenario" and f.polarity == "positive"
            }
        )
        technologies = sorted(
            {
                f.term
                for f in features.features
                if f.dimension == "tech" and f.polarity == "positive"
            }
        )
        if set(meta.scenario) != set(scenarios) or set(meta.tech) != set(technologies):
            reject("Metric tags differ from the actual positive JD features.")
        references.extend([snapshot.snapshot_id, meta.feature_set_id])
        return domain, list(scenarios) or [None], list(technologies) or [None], references

    @staticmethod
    def _greeting_version(
        connection: sqlite3.Connection, job: PipelineJob, meta: PipelineMeta, verified: bool
    ) -> str | None:
        if verified:
            version = meta.sent_greeting_version
            return version if version and not version.startswith("CONTENT_") else None
        if not job.draft_version or job.draft_version.startswith("CONTENT_") or not meta.intake_id:
            return None
        saved = connection.execute(
            "SELECT state_json FROM job_intakes WHERE intake_id = ? AND candidate_id = ?",
            (meta.intake_id, job.candidate_id),
        ).fetchone()
        intake = IntakeRecord.model_validate_json(saved[0]) if saved else None
        if intake is None or intake.batch_id is None:
            return None
        saved = connection.execute(
            "SELECT batch_json FROM outreach_batches WHERE batch_id = ?", (intake.batch_id,)
        ).fetchone()
        batch = OutreachBatch.model_validate_json(saved[0]) if saved else None
        if batch is None or batch.harness_version != job.draft_version:
            return None
        return (
            batch.harness_version
            if any(
                item.job_id == meta.normalized_job_id and item.text == job.draft_greeting
                for item in batch.items
            )
            else None
        )

    def _facts(self, connection: sqlite3.Connection, candidate_id: str) -> list[PipelineMetricFact]:
        facts = []
        for row in connection.execute(
            "SELECT pipeline_id FROM pipeline_jobs WHERE candidate_id = ? ORDER BY pipeline_id",
            (candidate_id,),
        ).fetchall():
            job, meta = self.repository.current(connection, row[0], candidate_id)
            frozen_job, frozen_meta = self._frozen(connection, job, meta)
            domain, scenarios, technologies, references = self._features(
                connection, frozen_job, frozen_meta
            )
            histories = [
                PipelineHistory.model_validate(dict(saved))
                for saved in connection.execute(
                    "SELECT * FROM pipeline_state_history WHERE pipeline_id = ? ORDER BY rowid",
                    (job.pipeline_id,),
                )
            ]
            times = {h.to_state: h.changed_at for h in histories}
            references.extend(h.evidence_reference for h in histories)
            verified = meta.proof_status == "verified"
            if verified:
                used = connection.execute(
                    "SELECT send_reference FROM pipeline_used_sends WHERE pipeline_id = ?",
                    (job.pipeline_id,),
                ).fetchall()
                if not used or job.sent_at is None or job.send_readback != "exact":
                    reject(
                        "Verified metrics need the original bound send proof and exact timestamp."
                    )
                references.extend(saved[0] for saved in used)
                times["greeting_sent"] = job.sent_at
                if meta.read_at is not None and "greeting_read" in times:
                    times["greeting_read"] = meta.read_at
                if job.resume_sent_at is not None and "resume_sent" in times:
                    times["resume_sent"] = job.resume_sent_at
            else:
                times = {
                    key: value
                    for key, value in times.items()
                    if key in {"draft_pending", "abandoned"}
                }
            cause: ExclusionReason | None = None
            if meta.proof_status == "proof_pending":
                cause = "proof_pending"
            elif job.state_reason in {"job_closed", "employer_rejected"}:
                cause = "job_closed" if job.state_reason == "job_closed" else "employer_rejected"
            elif job.salary_verified == "fail":
                cause = "hard_filter"
            for scenario in scenarios:
                for technology in technologies:
                    facts.append(
                        PipelineMetricFact(
                            pipeline_id=job.pipeline_id,
                            candidate_id=candidate_id,
                            job_id=job.job_id,
                            dimension_platform=job.platform,
                            dimension_domain=domain,
                            dimension_scenario=scenario,
                            dimension_tech=technology,
                            dimension_greeting_version=self._greeting_version(
                                connection, frozen_job, frozen_meta, verified
                            ),
                            dimension_resume_version=job.resume_version
                            if job.resume_sent_at
                            else None,
                            dimension_salary_band=salary_band(frozen_job.salary_max_k),
                            stage_times=times,
                            proof_verified=verified,
                            exclusion_reason=cause,
                            evidence_references=sorted(set(references)),
                        )
                    )
        return facts

    def facts(self, candidate_id: str) -> list[PipelineMetricFact]:
        with self.database.connect() as connection:
            connection.execute("BEGIN")
            return self._facts(connection, candidate_id)

    @staticmethod
    def _metric(
        connection: sqlite3.Connection, metric_id: str, candidate_id: str
    ) -> PipelineStageMetric:
        row = connection.execute(
            "SELECT m.* FROM pipeline_stage_metrics m JOIN pipeline_metric_context c "
            "ON c.metric_id = m.metric_id WHERE m.metric_id = ? AND c.candidate_id = ?",
            (metric_id, candidate_id),
        ).fetchone()
        if row is None:
            reject("Pipeline metric not found for this candidate.")
        return PipelineStageMetric.model_validate(dict(row))

    @staticmethod
    def _context(
        connection: sqlite3.Connection, metric_id: str, candidate_id: str
    ) -> tuple[PipelineMetricEvidence, PipelineMetricRequest]:
        row = connection.execute(
            "SELECT evidence_json, request_json FROM pipeline_metric_context "
            "WHERE metric_id = ? AND candidate_id = ?",
            (metric_id, candidate_id),
        ).fetchone()
        if row is None:
            reject("Pipeline metric evidence not found for this candidate.")
        return (
            PipelineMetricEvidence.model_validate_json(row[0]),
            PipelineMetricRequest.model_validate_json(row[1]),
        )

    def get_metric(self, metric_id: str, candidate_id: str) -> PipelineStageMetric:
        with self.database.connect() as connection:
            return self._metric(connection, metric_id, candidate_id)

    def get_evidence(self, metric_id: str, candidate_id: str) -> PipelineMetricEvidence:
        with self.database.connect() as connection:
            return self._context(connection, metric_id, candidate_id)[0]

    def get_diagnosis(self, diagnosis_id: str, candidate_id: str) -> PipelineDiagnosis:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM pipeline_diagnoses WHERE diagnosis_id = ? AND candidate_id = ?",
                (diagnosis_id, candidate_id),
            ).fetchone()
        if row is None:
            reject("Pipeline diagnosis not found for this candidate.")
        data = dict(row)
        for key in ("excluded_counts", "evidence_references"):
            data[key] = json.loads(data[key])
        return PipelineDiagnosis.model_validate(data)

    def _rule(self, rule_id: str, candidate_id: str) -> ConfirmedPipelineMetricRule:
        from jobagent.storage.pipeline_rules import PipelineRuleService

        return PipelineRuleService(self.database).metric_rule(rule_id, candidate_id)

    @staticmethod
    def _insert(
        connection: sqlite3.Connection, table: str, model: ContractModel,
        *, now: datetime | None = None,
    ) -> None:
        if table not in {"pipeline_stage_metrics", "pipeline_diagnoses"}:
            reject("Unsupported immutable pipeline analysis table.")
        if table == "pipeline_diagnoses":
            if not isinstance(model, PipelineDiagnosis):
                reject("A diagnosis write requires its authoritative contract.")
            require_pipeline_policy(connection, model.candidate_id, "diagnosis", now=now)
        data = model.model_dump(mode="json", exclude={"schema_version"})
        values = [
            json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            for value in data.values()
        ]
        connection.execute(
            f"INSERT INTO {table} ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})",
            values,
        )

    def _save_metric(
        self,
        connection: sqlite3.Connection,
        metric: PipelineStageMetric,
        evidence: PipelineMetricEvidence,
        request: PipelineMetricRequest,
    ) -> None:
        existing = connection.execute(
            "SELECT 1 FROM pipeline_stage_metrics WHERE metric_id = ?", (metric.metric_id,)
        ).fetchone()
        if existing:
            old = self._metric(connection, metric.metric_id, evidence.candidate_id)
            old_evidence, old_request = self._context(
                connection, metric.metric_id, evidence.candidate_id
            )
            if (old, old_evidence, old_request) != (metric, evidence, request):
                reject("Immutable metric ID has conflicting source evidence.")
            return
        self._insert(connection, "pipeline_stage_metrics", metric)
        connection.execute(
            "INSERT INTO pipeline_metric_context VALUES (?, ?, ?, ?, ?)",
            (
                metric.metric_id,
                evidence.candidate_id,
                evidence.source_digest,
                evidence.model_dump_json(),
                request.model_dump_json(),
            ),
        )

    def compute(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        try:
            public = PipelineMetricsComputeInput.model_validate(data)
        except ValidationError as error:
            raise ContractValidationError("Stored metric request is invalid.") from error
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            request = PipelineMetricRequest(
                candidate_id=public.candidate_id,
                window_start=public.window_start,
                window_end=public.window_end,
                scope=public.scope,
                rule=self._rule(public.rule_id, public.candidate_id) if public.rule_id else None,
            )
            result = compute_metrics(request, self._facts(connection, public.candidate_id), now=now)
            for metric, evidence in zip(result.metrics, result.evidence, strict=True):
                self._save_metric(connection, metric, evidence, request)
            return result.model_dump(mode="json")

    def fresh_evidence(
        self, metric_id: str, candidate_id: str, *, now: datetime
    ) -> PipelineMetricEvidence:
        with self.database.connect() as connection:
            connection.execute("BEGIN")
            original = self._metric(connection, metric_id, candidate_id)
            _, request = self._context(connection, metric_id, candidate_id)
            if (
                request.rule is not None
                and self._rule(request.rule.rule_id, candidate_id) != request.rule
            ):
                reject("Original metric rule is no longer the same active owner-confirmed rule.")
            result = compute_metrics(request, self._facts(connection, candidate_id), now=now)
        for metric, evidence in zip(result.metrics, result.evidence, strict=True):
            if (metric.stage_from, metric.stage_to) == (original.stage_from, original.stage_to):
                return evidence.model_copy(update={"metric_id": metric_id})
        reject("Original funnel segment is missing from the reconstructed metric evidence.")

    def diagnose(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        try:
            public = PipelineStoredDiagnosisInput.model_validate(data)
            public = public.model_copy(
                update={
                    "current_metric_ids": sorted(public.current_metric_ids),
                    "previous_metric_ids": sorted(set(public.previous_metric_ids)),
                }
            )
        except ValidationError as error:
            raise ContractValidationError("Stored diagnosis request is invalid.") from error
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            require_pipeline_policy(connection, public.candidate_id, "diagnosis", now=now)
            current = [
                self._metric(connection, key, public.candidate_id)
                for key in public.current_metric_ids
            ]
            previous = [
                self._metric(connection, key, public.candidate_id)
                for key in public.previous_metric_ids
            ]
            evidence = [
                self._context(connection, key, public.candidate_id)[0]
                for key in public.current_metric_ids
            ]
            request = PipelineDiagnosisRequest(
                candidate_id=public.candidate_id,
                current=current,
                previous=previous,
                evidence=evidence,
                exclusions_reviewed=public.exclusions_reviewed,
                review_reference=public.review_reference,
                rule=self._rule(public.rule_id, public.candidate_id) if public.rule_id else None,
            )
            decision = diagnose(request, now=now)
            digest = canonical_digest(
                [public.model_dump(mode="json"), decision.model_dump(mode="json")]
            )
            report_id = "PDREPORT_" + digest[7:31].upper()
            existing = connection.execute(
                "SELECT report_json FROM pipeline_diagnosis_reports "
                "WHERE report_id = ? AND candidate_id = ?",
                (report_id, public.candidate_id),
            ).fetchone()
            if existing:
                result: dict[str, object] = json.loads(existing[0])
                return result
            for item in decision.diagnoses:
                self._insert(connection, "pipeline_diagnoses", item, now=now)
                original = self._metric(connection, item.metric_id, public.candidate_id)
                old_evidence, old_request = self._context(
                    connection, item.metric_id, public.candidate_id
                )
                linked_id = (
                    original.metric_id + "_D_" + canonical_digest(item.diagnosis_id)[7:15].upper()
                )
                linked = original.model_copy(
                    update={"metric_id": linked_id, "diagnosis_id": item.diagnosis_id}
                )
                self._save_metric(
                    connection,
                    linked,
                    old_evidence.model_copy(update={"metric_id": linked_id}),
                    old_request,
                )
            result = {
                **decision.model_dump(mode="json"),
                "report_id": report_id,
                "review_reference": public.review_reference,
            }
            connection.execute(
                "INSERT INTO pipeline_diagnosis_reports VALUES (?, ?, ?, ?, ?)",
                (
                    report_id,
                    public.candidate_id,
                    digest,
                    json.dumps(result, ensure_ascii=False),
                    now.isoformat(),
                ),
            )
            return result
