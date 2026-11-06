"""Read-only projection of listed first greetings and the person's decisions on them."""

import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.console import ConsoleOutreachDecision, ConsoleSource
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAsk,
    OutreachAudit,
    OutreachBatch,
    OutreachItem,
    OutreachResult,
)
from jobagent.schemas.sourcing_feedback import PagedCardState

_REQUIRED = {
    "outreach_batches", "outreach_asks", "outreach_approvals", "outreach_withdrawals",
    "outreach_audits", "evidence_items",
}


def _owned(item: OutreachItem, candidate_id: str, evidence: set[str]) -> bool:
    if item.source_binding is not None:
        return item.source_binding.candidate_id == candidate_id
    return bool(item.evidence_ids) and set(item.evidence_ids) <= evidence


def read_outreach_decisions(
    database: Path, candidate_id: str
) -> tuple[list[ConsoleOutreachDecision], ConsoleSource]:
    if not database.exists():
        return [], ConsoleSource(
            name="approvals", status="missing", message="Local database is missing."
        )
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            return _read(connection, candidate_id), ConsoleSource(
                name="approvals", status="complete",
                message="Listed greetings tied to this candidate by confirmed evidence or "
                "source binding; others are not joined. Projection only; grants nothing.",
            )
    except (OSError, sqlite3.Error, ValidationError, ValueError):
        return [], ConsoleSource(
            name="approvals", status="invalid", message="Outreach ledger unavailable."
        )


def _read(connection: sqlite3.Connection, candidate_id: str) -> list[ConsoleOutreachDecision]:
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not tables >= _REQUIRED:
        return []
    evidence = {
        item.id
        for item in (
            EvidenceItem.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT evidence_json FROM evidence_items WHERE candidate_id = ?", (candidate_id,)
            )
        )
        if item.user_confirmed and item.confidence.value != "weak"
    }
    batches = [
        OutreachBatch.model_validate_json(row[0])
        for row in connection.execute("SELECT batch_json FROM outreach_batches")
    ]
    asks: dict[str, OutreachAsk] = {}
    for row in connection.execute("SELECT ask_json FROM outreach_asks"):
        posed = OutreachAsk.model_validate_json(row[0])
        if posed.batch_id not in asks or asks[posed.batch_id].asked_at < posed.asked_at:
            asks[posed.batch_id] = posed
    approvals = {
        approval.batch_id: approval
        for approval in (
            OutreachApproval.model_validate_json(row[0])
            for row in connection.execute("SELECT approval_json FROM outreach_approvals")
        )
    }
    withdrawn = {row[0] for row in connection.execute("SELECT batch_id FROM outreach_withdrawals")}
    audits: dict[tuple[str, int, str], OutreachAudit] = {}
    for row in connection.execute("SELECT audit_json FROM outreach_audits ORDER BY recorded_at"):
        attempt = OutreachAudit.model_validate_json(row[0])
        audits[(attempt.batch_id, attempt.number, attempt.item_digest)] = attempt
    states: dict[str, list[PagedCardState]] = {}
    if "paged_card_states" in tables:
        for row in connection.execute("SELECT state_json FROM paged_card_states"):
            state = PagedCardState.model_validate_json(row[0])
            if state.candidate_id in {None, candidate_id} and not state.demo_mode:
                states.setdefault(state.batch_id, []).append(state)
    item_decided_batches = {
        child for group in states.values() for state in group
        for child in state.approved_batches.values()
    }
    result = []
    for batch in sorted(batches, key=lambda b: (b.created_at, b.batch_id)):
        ask = asks.get(batch.batch_id)
        approval = approvals.get(batch.batch_id)
        if approval is not None and approval.batch_digest != batch.batch_digest:
            approval = None
        decisions: dict[str, str] = {}
        drafts: dict[str, str] = {}
        for state in states.get(batch.batch_id, []):
            decisions.update(state.decisions)
            drafts.update(state.drafts)
        for item in batch.items:
            if not _owned(item, candidate_id, evidence):
                continue
            decided = decisions.get(str(item.number))
            if decided == "approved":
                continue  # Its single-item approval list carries the row.
            view = ConsoleOutreachDecision(
                batch_id=batch.batch_id, ask_id=ask.ask_id if ask else None, number=item.number,
                job_id=item.job_id, platform=item.platform, company=item.company,
                title=item.title, text=item.text, item_digest=item.item_digest,
                asked_at=ask.asked_at if ask else None, state="not_asked",
            )
            if approval is not None and item.number in approval.approved_numbers:
                view.state = "approved"
                view.decided_via = (
                    "item_decision" if batch.batch_id in item_decided_batches else "batch_approval"
                )
                view.approval_id = approval.approval_id
                view.approved_at = approval.approved_at
                view.approval_attestation = approval.attestation
            elif decided in {"declined", "revision_requested"}:
                view.state = decided  # type: ignore[assignment]
                view.decided_via = "item_decision"
                if decided == "revision_requested":
                    view.revised_text = drafts.get(str(item.number))
            elif approval is not None:
                view.state, view.decided_via = "not_selected", "batch_approval"
            elif batch.batch_id in withdrawn:
                view.state = "withdrawn"
            elif ask is not None:
                view.state = "awaiting_answer"
            audit = audits.get((batch.batch_id, item.number, item.item_digest))
            if audit is not None:
                view.send_result = audit.result.value
                if audit.result is OutreachResult.SENT:
                    view.sent_at = audit.recorded_at
            result.append(view)
    return result
