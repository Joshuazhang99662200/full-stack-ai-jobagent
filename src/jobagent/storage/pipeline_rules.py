"""Cumulative-diagnosis proposals share the existing owner-confirmed rule ledger."""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.schemas.pipeline_metrics import (
    ConfirmedPipelineMetricRule,
    PipelineDiagnosis,
    PipelineSlice,
)
from jobagent.schemas.pipeline_rules import (
    PipelineRuleConfirmationInput,
    PipelineRuleProposalInput,
    PipelineRuleReviewInput,
)
from jobagent.storage.database import Database
from jobagent.storage.message_diff_repository import MessageDiffRepository


class PipelineRuleService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.rules = MessageDiffRepository(database)

    def proposal(self, proposal_id: str, candidate_id: str) -> dict[str, object]:
        result = self.rules.proposal(proposal_id, candidate_id)
        if result.get("source_kind") != "pipeline_diagnosis":
            reject("This is not a pipeline diagnosis proposal.")
        return result

    def confirmed(self, candidate_id: str) -> list[dict[str, object]]:
        return self.rules.confirmed_rules(candidate_id)

    def diagnosis(self, diagnosis_id: str, candidate_id: str) -> PipelineDiagnosis:
        from jobagent.storage.pipeline_metrics import PipelineMetricsService

        return PipelineMetricsService(self.database).get_diagnosis(diagnosis_id, candidate_id)

    def require_current_evidence(self, diagnosis: PipelineDiagnosis, *, now: datetime) -> None:
        from jobagent.storage.pipeline_metrics import PipelineMetricsService

        if now.tzinfo is None or diagnosis.window_end > now:
            reject("Rule evidence must come from an already closed observed window.")
        metrics = PipelineMetricsService(self.database)
        saved = metrics.get_evidence(diagnosis.metric_id, diagnosis.candidate_id)
        fresh = metrics.fresh_evidence(diagnosis.metric_id, diagnosis.candidate_id, now=now)
        if saved.source_digest != fresh.source_digest:
            reject("Metric facts changed; compute a fresh diagnosis before deciding its rule.")

    @staticmethod
    def scope(diagnosis: PipelineDiagnosis) -> dict[str, object]:
        return PipelineSlice.model_validate(
            diagnosis.model_dump(include=set(PipelineSlice.model_fields))
        ).model_dump(mode="json")

    def scope_state(self, candidate_id: str, scope: object, category: object) -> str:
        items = [
            (str(p["proposal_id"]), str(p["rule_hash"]))
            for p in self.confirmed(candidate_id)
            if p.get("source_kind") == "pipeline_diagnosis"
            and p.get("scope") == scope
            and p.get("category") == category
        ]
        return canonical_digest(sorted(items))

    @staticmethod
    def existing(
        connection: sqlite3.Connection, proposal_id: str, candidate_id: str, digest: str
    ) -> dict[str, object] | None:
        row = connection.execute(
            "SELECT * FROM message_rule_proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        if row:
            if row["candidate_id"] != candidate_id or row["input_digest"] != digest:
                reject("Proposal ID cannot change its original diagnosis, scope or text.")
            result: dict[str, object] = json.loads(row["proposal_json"])
            return result
        return None

    def save_proposal(
        self,
        connection: sqlite3.Connection,
        *,
        proposal_id: str,
        candidate_id: str,
        diagnosis: PipelineDiagnosis,
        category: str,
        before: object,
        after: object,
        previous_id: str | None,
        operation: str,
        input_digest: str,
        now: datetime,
        restore_id: str | None = None,
    ) -> dict[str, object]:
        scope = self.scope(diagnosis)
        effect = dict(
            scope=scope,
            category=category,
            rule_text_before=before,
            rule_text_after=after,
            previous_proposal_id=previous_id,
            restore_proposal_id=restore_id,
            operation=operation,
            diagnosis_id=diagnosis.diagnosis_id,
            diagnosis_digest=diagnosis.source_digest,
        )
        result: dict[str, object] = {
            **effect,
            "proposal_id": proposal_id,
            "candidate_id": candidate_id,
            "source_kind": "pipeline_diagnosis",
            "rule_hash": canonical_digest(effect),
            "rule_text": after if after is not None else before,
            "report_digest": diagnosis.source_digest,
            "created_at": now.isoformat(),
            "stage_from": diagnosis.stage_from,
            "stage_to": diagnosis.stage_to,
            "baseline_rate": str(diagnosis.sliced_cumulative_rate),
            "evidence_references": diagnosis.evidence_references,
            "scoped_state_digest": self.scope_state(candidate_id, scope, category),
            "status": "awaiting_owner_confirmation",
        }
        connection.execute(
            "INSERT INTO message_rule_proposals VALUES (?, ?, ?, ?)",
            (proposal_id, candidate_id, input_digest, json.dumps(result, ensure_ascii=False)),
        )
        return result

    def propose(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = PipelineRuleProposalInput.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            old = self.existing(connection, request.proposal_id, request.candidate_id, digest)
            if old:
                return old
            diagnosis = self.diagnosis(request.diagnosis_id, request.candidate_id)
            if (
                request.diagnosis_digest != diagnosis.source_digest
                or diagnosis.diagnosis_code.startswith("optimization_")
                or diagnosis.sliced_cumulative_rate is None
                or not request.rule_text_after.strip()
            ):
                reject("A proposal needs a matching actionable diagnosis and exact scoped rule.")
            self.require_current_evidence(diagnosis, now=now)
            if request.previous_proposal_id:
                previous = next(
                    (
                        p
                        for p in self.confirmed(request.candidate_id)
                        if p["proposal_id"] == request.previous_proposal_id
                    ),
                    None,
                )
                if (
                    previous is None
                    or previous.get("scope") != self.scope(diagnosis)
                    or previous.get("category") != request.category
                    or previous.get("rule_text") != request.rule_text_before
                ):
                    reject("The proposed before-text must match the actual active scoped rule.")
            elif request.rule_text_before is not None:
                reject("Before-text needs the specific currently confirmed rule it describes.")
            return self.save_proposal(
                connection,
                proposal_id=request.proposal_id,
                candidate_id=request.candidate_id,
                diagnosis=diagnosis,
                category=request.category,
                before=request.rule_text_before,
                after=request.rule_text_after,
                previous_id=request.previous_proposal_id,
                operation="activate",
                input_digest=digest,
                now=now,
            )

    @staticmethod
    def decision(
        connection: sqlite3.Connection,
        confirmation_id: str,
        candidate_id: str,
        proposal: dict[str, object],
        *,
        accepted: bool,
        digest: str,
        owner_text: str,
        owner_reference: str,
        now: datetime,
        via: dict[str, object] | None = None,
        baseline: object = None,
        owner_accepted_effect: bool | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = dict(
            confirmation_id=confirmation_id,
            proposal_id=proposal["proposal_id"],
            candidate_id=candidate_id,
            rule_hash=proposal["rule_hash"],
            accepted=accepted,
            owner_text=owner_text,
            owner_reference=owner_reference,
            decided_at=now.isoformat(),
            effective_at=now.isoformat(),
            source_kind="pipeline_diagnosis",
            via_proposal_id=via["proposal_id"] if via else None,
            via_rule_hash=via["rule_hash"] if via else None,
            baseline_override=baseline,
            owner_accepted_effect=accepted
            if owner_accepted_effect is None
            else owner_accepted_effect,
        )
        connection.execute(
            "INSERT INTO message_rule_confirmations VALUES (?, ?, ?, ?, ?)",
            (
                confirmation_id,
                candidate_id,
                proposal["proposal_id"],
                digest,
                json.dumps(result, ensure_ascii=False),
            ),
        )
        return result

    def confirm(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = PipelineRuleConfirmationInput.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT * FROM message_rule_confirmations WHERE confirmation_id = ?",
                (request.confirmation_id,),
            ).fetchone()
            if old:
                if old["candidate_id"] != request.candidate_id or old["input_digest"] != digest:
                    reject("Owner decision ID cannot change its exact original decision.")
                replay: dict[str, object] = json.loads(old["confirmation_json"])
                return replay
            proposal = self.proposal(request.proposal_id, request.candidate_id)
            if (
                request.rule_hash != proposal["rule_hash"]
                or not request.owner_text.strip()
                or not request.owner_reference.strip()
                or now.tzinfo is None
            ):
                reject(
                    "An owner decision must bind the exact rule effect, scope and original reply."
                )
            if request.accepted:
                diagnosis = self.diagnosis(str(proposal["diagnosis_id"]), request.candidate_id)
                self.require_current_evidence(diagnosis, now=now)
                if proposal["scoped_state_digest"] != self.scope_state(
                    request.candidate_id, proposal["scope"], proposal["category"]
                ):
                    reject("Applicable confirmed rules changed; review a fresh proposal.")
                previous_id = proposal.get("previous_proposal_id")
                if previous_id:
                    previous = self.proposal(str(previous_id), request.candidate_id)
                    self.decision(
                        connection,
                        request.confirmation_id + "_WITHDRAW",
                        request.candidate_id,
                        previous,
                        accepted=False,
                        digest=canonical_digest([digest, "withdraw"]),
                        owner_text=request.owner_text,
                        owner_reference=request.owner_reference,
                        now=now,
                        via=proposal,
                    )
                restore_id = proposal.get("restore_proposal_id")
                if restore_id:
                    restored = self.proposal(str(restore_id), request.candidate_id)
                    self.decision(
                        connection,
                        request.confirmation_id + "_RESTORE",
                        request.candidate_id,
                        restored,
                        accepted=True,
                        digest=canonical_digest([digest, "restore"]),
                        owner_text=request.owner_text,
                        owner_reference=request.owner_reference,
                        now=now,
                        via=proposal,
                        baseline=proposal["baseline_rate"],
                    )
            active = request.accepted and proposal["operation"] == "activate"
            result = self.decision(
                connection,
                request.confirmation_id,
                request.candidate_id,
                proposal,
                accepted=active,
                digest=digest,
                owner_text=request.owner_text,
                owner_reference=request.owner_reference,
                now=now,
                owner_accepted_effect=request.accepted,
            )
            # The ledger records effective rule acceptance; the full effect remains in the proposal.
            return result

    def metric_rule(self, rule_id: str, candidate_id: str) -> ConfirmedPipelineMetricRule:
        proposal = next(
            (p for p in self.confirmed(candidate_id) if p["proposal_id"] == rule_id), None
        )
        if proposal is None or proposal.get("source_kind") != "pipeline_diagnosis":
            reject("Optimization needs an actually owner-confirmed pipeline rule.")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT confirmation_json FROM message_rule_confirmations "
                "WHERE proposal_id = ? AND candidate_id = ? ORDER BY rowid DESC LIMIT 1",
                (rule_id, candidate_id),
            ).fetchone()
        decision: dict[str, object] = json.loads(row[0])
        baseline = decision.get("baseline_override")
        return ConfirmedPipelineMetricRule.model_validate(
            dict(
                rule_id=rule_id,
                candidate_id=candidate_id,
                scope=proposal["scope"],
                stage_from=proposal["stage_from"],
                stage_to=proposal["stage_to"],
                confirmed_at=decision["decided_at"],
                effective_at=decision["effective_at"],
                pre_rule_cumulative_rate=Decimal(
                    str(baseline if baseline is not None else proposal["baseline_rate"])
                ),
                owner_confirmation_reference=decision["owner_reference"],
            )
        )

    def review(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = PipelineRuleReviewInput.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT * FROM pipeline_rule_reviews WHERE review_id = ?", (request.review_id,)
            ).fetchone()
            if old:
                if old["input_digest"] != digest or old["candidate_id"] != request.candidate_id:
                    reject("Optimization review ID has different original evidence.")
                result: dict[str, object] = json.loads(old["report_json"])
                return result
            active = self.metric_rule(request.rule_id, request.candidate_id)
            diagnosis = self.diagnosis(request.diagnosis_id, request.candidate_id)
            if (
                diagnosis.rule_id != active.rule_id
                or diagnosis.source_digest != request.diagnosis_digest
                or diagnosis.diagnosis_code
                not in {"optimization_effective", "optimization_ineffective"}
                or self.scope(diagnosis) != active.scope.model_dump(mode="json")
            ):
                reject(
                    "Review must bind the confirmed rule and its exact optimization diagnosis."
                )
            self.require_current_evidence(diagnosis, now=now)
            result = dict(
                review_id=request.review_id,
                candidate_id=request.candidate_id,
                diagnosis_id=diagnosis.diagnosis_id,
                rule_id=active.rule_id,
                outcome=diagnosis.diagnosis_code,
                rules_changed=False,
                rollback_proposal=None,
            )
            if diagnosis.diagnosis_code == "optimization_ineffective":
                original = self.proposal(active.rule_id, request.candidate_id)
                restore_id = original.get("previous_proposal_id")
                restore = (
                    self.proposal(str(restore_id), request.candidate_id) if restore_id else None
                )
                rollback = self.save_proposal(
                    connection,
                    proposal_id="ROLLBACK_"
                    + canonical_digest([request.review_id, active.rule_id])[7:31],
                    candidate_id=request.candidate_id,
                    diagnosis=diagnosis,
                    category=str(original["category"]),
                    before=original["rule_text"],
                    after=restore["rule_text"] if restore else None,
                    previous_id=active.rule_id,
                    operation="restore" if restore else "withdraw",
                    input_digest=canonical_digest([digest, "rollback"]),
                    now=now,
                    restore_id=str(restore_id) if restore_id else None,
                )
                result["rollback_proposal"] = rollback
            connection.execute(
                "INSERT INTO pipeline_rule_reviews VALUES (?, ?, ?, ?, ?)",
                (
                    request.review_id,
                    request.candidate_id,
                    digest,
                    json.dumps(result, ensure_ascii=False),
                    now.isoformat(),
                ),
            )
            return result
