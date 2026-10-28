"""Private comparison ledger. Review eligibility never grants a generation preference."""

import json
from datetime import datetime

from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.message_diff import CATEGORIES, compare
from jobagent.schemas.message_diff import (
    MessageDiffInput,
    MessageDiffResult,
    MessageRuleConfirmation,
    MessageRuleProposal,
)
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


class MessageDiffRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = MessageDiffInput.model_validate(data)
        result = compare(request)
        if request.occurred_at > now:
            reject("A comparison cannot claim a future edit.")
        if SqliteJobRepository(self.database).get_job(request.job_id) is None:
            reject("Comparison needs the actual cached job identity.")
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT * FROM message_diff_events WHERE event_id = ?", (request.event_id,)
            ).fetchone()
            if old:
                if old["input_digest"] != digest or old["candidate_id"] != request.candidate_id:
                    reject("Comparison event ID cannot change its original text or context.")
                return MessageDiffResult.model_validate_json(old["result_json"]).model_dump(
                    mode="json"
                )
            episodes = connection.execute(
                "SELECT input_json FROM message_diff_events WHERE candidate_id = ? AND job_id = ? "
                "AND draft_reference = ?",
                (request.candidate_id, request.job_id, request.draft_reference),
            ).fetchall()
            if any(
                MessageDiffInput.model_validate_json(row[0]).initial_hash != request.initial_hash
                for row in episodes
            ):
                reject("The initial draft is immutable within one comparison episode.")
            connection.execute(
                "INSERT INTO message_diff_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    request.event_id,
                    request.candidate_id,
                    request.job_id,
                    request.draft_reference,
                    digest,
                    request.model_dump_json(),
                    result.model_dump_json(),
                ),
            )
        return result.model_dump(mode="json")

    def report(self, candidate_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT input_json, result_json FROM message_diff_events "
                "WHERE candidate_id = ? ORDER BY rowid",
                (candidate_id,),
            ).fetchall()
        latest: dict[tuple[str, str], tuple[MessageDiffInput, MessageDiffResult]] = {}
        for row in rows:
            request = MessageDiffInput.model_validate_json(row["input_json"])
            result = MessageDiffResult.model_validate_json(row["result_json"])
            key = (request.job_id, request.draft_reference)
            if key not in latest or request.occurred_at >= latest[key][0].occurred_at:
                latest[key] = (request, result)
        categories: dict[str, object] = {}
        evaluation = []
        identity = {}
        for request, _ in latest.values():
            job = SqliteJobRepository(self.database).get_job(request.job_id)
            assert job is not None
            identity[request.job_id] = (job.source.casefold(), job.source_job_id.casefold())
        for category in CATEGORIES:
            jobs = sorted(
                {
                    request.job_id
                    for request, result in latest.values()
                    if result.changed and category in result.categories
                }
            )
            distinct = {identity[job_id] for job_id in jobs}
            count = len(distinct)
            categories[category] = {
                "sample_count": count,
                "job_ids": jobs,
                "maturity": "stable"
                if count >= 3
                else "repeated"
                if count == 2
                else "observed_once"
                if count == 1
                else "none",
            }
            if count >= 3:
                evaluation.append(category)
        report: dict[str, object] = {
            "candidate_id": candidate_id,
            "categories": categories,
            "evaluation_candidates": evaluation,
            "total_changed_samples": sum(result.changed for _, result in latest.values()),
            "unclassified_samples": sum(
                result.changed and not result.categories for _, result in latest.values()
            ),
            "latest_events": sorted(request.event_id for request, _ in latest.values()),
            "generation_rules_updated": False,
            "send_proof_verified": False,
            "semantic_classification": "host_or_user_proposal",
        }
        report["report_digest"] = canonical_digest(report)
        return report

    def propose(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = MessageRuleProposal.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection:
            old = connection.execute(
                "SELECT * FROM message_rule_proposals WHERE proposal_id = ?", (request.proposal_id,)
            ).fetchone()
        if old:
            if old["input_digest"] != digest or old["candidate_id"] != request.candidate_id:
                reject("Rule proposal ID cannot change its exact text or report.")
            replay: dict[str, object] = json.loads(old["proposal_json"])
            return replay
        report = self.report(request.candidate_id)
        eligible = report["evaluation_candidates"]
        assert isinstance(eligible, list)
        if (
            request.report_digest != report["report_digest"]
            or request.category not in eligible
            or not request.rule_text.strip()
        ):
            reject("Promotion needs a current report with three different jobs and an exact rule.")
        proposal: dict[str, object] = {
            **request.model_dump(mode="json"),
            "rule_hash": text_digest(request.rule_text),
            "created_at": now.isoformat(),
            "status": "awaiting_owner_confirmation",
        }
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO message_rule_proposals VALUES (?, ?, ?, ?)",
                (
                    request.proposal_id,
                    request.candidate_id,
                    digest,
                    json.dumps(proposal, ensure_ascii=False),
                ),
            )
        return proposal

    def proposal(self, proposal_id: str, candidate_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT proposal_json FROM message_rule_proposals "
                "WHERE proposal_id = ? AND candidate_id = ?",
                (proposal_id, candidate_id),
            ).fetchone()
        if row is None:
            reject("Rule proposal not found for this candidate.")
        result: dict[str, object] = json.loads(row[0])
        return result

    def confirm(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = MessageRuleConfirmation.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection:
            old = connection.execute(
                "SELECT * FROM message_rule_confirmations WHERE confirmation_id = ?",
                (request.confirmation_id,),
            ).fetchone()
        if old:
            if old["input_digest"] != digest or old["candidate_id"] != request.candidate_id:
                reject("Owner decision ID cannot change its original approval.")
            replay: dict[str, object] = json.loads(old["confirmation_json"])
            return replay
        proposal = self.proposal(request.proposal_id, request.candidate_id)
        if (
            request.rule_hash != proposal["rule_hash"]
            or not request.owner_text.strip()
            or not request.owner_reference.strip()
        ):
            reject("Owner must decide the exact proposed rule with the original reply reference.")
        if (
            request.accepted
            and proposal["report_digest"] != self.report(request.candidate_id)["report_digest"]
        ):
            reject("Comparison evidence changed; review a fresh rule proposal before confirming.")
        confirmation: dict[str, object] = {
            **request.model_dump(mode="json"),
            "decided_at": now.isoformat(),
        }
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO message_rule_confirmations VALUES (?, ?, ?, ?, ?)",
                (
                    request.confirmation_id,
                    request.candidate_id,
                    request.proposal_id,
                    digest,
                    json.dumps(confirmation, ensure_ascii=False),
                ),
            )
        return confirmation

    def confirmed_rules(self, candidate_id: str) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT confirmation_json FROM message_rule_confirmations "
                "WHERE candidate_id = ? ORDER BY rowid",
                (candidate_id,),
            ).fetchall()
        latest: dict[str, dict[str, object]] = {}
        for row in rows:
            item: dict[str, object] = json.loads(row[0])
            latest[str(item["proposal_id"])] = item
        return [
            {
                **self.proposal(key, candidate_id),
                "status": "owner_confirmed",
                "confirmation_id": decision["confirmation_id"],
            }
            for key, decision in latest.items()
            if decision["accepted"]
        ]
