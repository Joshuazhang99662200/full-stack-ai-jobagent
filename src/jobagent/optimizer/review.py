"""Bind independent semantic review to artifacts and check complete item coverage."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from jobagent.optimizer.verification import ClaimVerifier
from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.optimizer import (
    ClaimLedger,
    ClaimReviewSet,
    TailoredDraft,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)


def content_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def draft_digest(draft: TailoredDraft) -> str:
    return content_digest(draft.model_dump(mode="json"))


def evidence_digest(evidence: Sequence[EvidenceItem]) -> str:
    return content_digest([e.model_dump(mode="json") for e in sorted(evidence, key=lambda e: e.id)])


def _normalized(text: str) -> str:
    return "".join(text.split())


def verify_draft(
    draft: TailoredDraft,
    evidence: Sequence[EvidenceItem],
    review: ClaimReviewSet | None,
) -> VerificationReport:
    issues: list[VerificationIssue] = []
    claims = draft.claim_ledger.claims
    claim_ids = [c.claim_id for c in claims]
    item_ids = [item.id for item in draft.items]
    if len(set(claim_ids)) != len(claim_ids) or len(set(item_ids)) != len(item_ids):
        issues.append(
            VerificationIssue(code="duplicate_id", message="Item and claim IDs must be unique.")
        )
    if not draft.items:
        issues.append(VerificationIssue(code="empty_resume", message="Resume items are required."))
    for item in draft.items:
        associated = [c for c in claims if c.resume_item_id == item.id]
        if not associated or _normalized("".join(c.text for c in associated)) != _normalized(
            item.text
        ):
            issues.append(
                VerificationIssue(
                    code="uncovered_item_text",
                    message="The ledger must cover the complete item text in order.",
                    resume_item_id=item.id,
                )
            )
        if {e for c in associated for e in c.evidence_ids} != set(item.evidence_ids):
            issues.append(
                VerificationIssue(
                    code="item_evidence_mismatch",
                    message="Item and claim evidence references differ.",
                    resume_item_id=item.id,
                )
            )
    for claim in claims:
        if claim.resume_item_id not in item_ids:
            issues.append(
                VerificationIssue(
                    code="orphan_claim",
                    message="Claim cites a missing resume item.",
                    claim_id=claim.claim_id,
                )
            )
    valid_review = review is not None
    if review is None:
        issues.append(
            VerificationIssue(
                code="review_required", message="Independent semantic review is required."
            )
        )
    elif review.draft_digest != draft_digest(draft) or review.evidence_digest != evidence_digest(
        evidence
    ):
        valid_review = False
        issues.append(
            VerificationIssue(
                code="stale_review", message="Review digests do not match current artifacts."
            )
        )
    elif sorted(r.claim_id for r in review.reviews) != sorted(claim_ids):
        valid_review = False
        issues.append(
            VerificationIssue(
                code="review_coverage", message="Review must judge each claim exactly once."
            )
        )
    judgements = (
        {r.claim_id: r for r in review.reviews} if review is not None and valid_review else {}
    )
    effective = ClaimLedger(
        claims=[
            c.model_copy(
                update={
                    "verification_status": judgements[c.claim_id].status
                    if c.claim_id in judgements
                    else VerificationStatus.UNSUPPORTED,
                }
            )
            for c in claims
        ]
    )
    report = ClaimVerifier().verify(effective, evidence)
    if issues:
        report = report.model_copy(update={"passed": False, "issues": report.issues + issues})
    return report
