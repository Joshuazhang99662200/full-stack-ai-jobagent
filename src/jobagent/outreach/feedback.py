"""Turn the person's answer about an asked list into bounded feedback events.

Pure: no storage, no host calls. Feedback shapes later priorities and drafts;
it never approves, sends or rewrites an approval. An "approve" signal only
mirrors an approval that was already registered through the approval gate.
"""

from collections.abc import Mapping

from jobagent.digest import canonical_digest, text_digest
from jobagent.errors import ContractValidationError
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.outreach import OutreachApproval, OutreachAsk, OutreachBatch
from jobagent.schemas.sourcing_feedback import (
    OutreachFeedbackLink,
    OutreachFeedbackRequest,
    SourcingFeedback,
)


def feedback_event_id(ask_id: str, number: int) -> str:
    """One decision per asked item: the same item always maps to the same event."""
    return "OFB_" + canonical_digest([ask_id, number]).removeprefix("sha256:")[:24].upper()


def build_outreach_feedback(
    request: OutreachFeedbackRequest,
    *,
    batch: OutreachBatch,
    ask: OutreachAsk,
    approval: OutreachApproval | None,
    jobs: Mapping[str, NormalizedJob],
    owned_evidence_ids: set[str],
) -> list[tuple[SourcingFeedback, OutreachFeedbackLink]]:
    if (
        batch.batch_id != request.batch_id
        or ask.ask_id != request.ask_id
        or ask.batch_id != batch.batch_id
        or ask.batch_digest != batch.batch_digest
        or ask.policy_digest != batch.policy_digest
    ):
        raise ContractValidationError("Feedback must answer the exact list that was asked.")
    if request.occurred_at < ask.asked_at:
        raise ContractValidationError("Feedback predates the question that was asked.")
    approved: set[int] = set()
    if approval is not None:
        if approval.batch_digest != batch.batch_digest or approval.ask_id not in {None, ask.ask_id}:
            raise ContractValidationError("The recorded approval belongs to another list.")
        approved = set(approval.approved_numbers)
    listed = {item.number: item for item in batch.items}
    records = []
    for decision in request.items:
        item = listed.get(decision.number)
        if item is None:
            raise ContractValidationError(
                "Feedback names an item that is not on the asked list.",
                details={"number": decision.number},
            )
        if not item.evidence_ids or not set(item.evidence_ids) <= owned_evidence_ids:
            raise ContractValidationError(
                "The listed item is not grounded in this candidate's confirmed evidence.",
                details={"number": decision.number},
            )
        job = jobs.get(item.job_id)
        if job is None:
            raise ContractValidationError(
                "The listed job is not stored.", details={"number": decision.number}
            )
        if decision.action == "approve" and decision.number not in approved:
            raise ContractValidationError(
                "An approve signal needs a recorded approval for this item; "
                "register the person's answer with `outreach approve` first.",
                details={"number": decision.number},
            )
        if decision.action != "approve" and decision.number in approved:
            raise ContractValidationError(
                "This item is already approved; feedback cannot contradict the approval.",
                details={"number": decision.number},
            )
        words = decision.revised_text or item.text
        if decision.action == "revise" and words.strip() == item.text.strip():
            raise ContractValidationError(
                "A revision must change the greeting.", details={"number": decision.number}
            )
        event_id = feedback_event_id(ask.ask_id, decision.number)
        event = SourcingFeedback(
            event_id=event_id,
            idempotency_key=event_id,
            job_id=item.job_id,
            source=item.platform,
            query_strategy_version=request.query_strategy_version,
            action=decision.action,
            reason_category=decision.reason_category,
            free_text=decision.free_text,
            content_digest=text_digest(words),
            actor_id=request.actor_id,
            occurred_at=request.occurred_at,
            candidate_id=request.candidate_id,
            original_text=item.text,
            revised_text=decision.revised_text,
            jd_text=job.jd_raw,
            job_title=item.title,
            company=item.company,
        )
        link = OutreachFeedbackLink(
            event_id=event_id,
            batch_id=batch.batch_id,
            ask_id=ask.ask_id,
            item_number=decision.number,
            words=words,
            attestation=request.attestation,
        )
        records.append((event, link))
    return records
