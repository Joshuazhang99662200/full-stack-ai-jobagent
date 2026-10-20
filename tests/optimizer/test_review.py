from jobagent.optimizer.review import draft_digest, evidence_digest, verify_draft
from jobagent.schemas.optimizer import (
    ClaimLedger,
    ClaimReview,
    ClaimReviewSet,
    KeywordCoverageReport,
    OptimizedResumeItem,
    TailoredDraft,
    VerificationStatus,
)
from tests.optimizer.test_verification import claim, evidence


def draft():
    return TailoredDraft(
        items=[
            OptimizedResumeItem(
                id="ITEM_1", section="experience", text=claim().text, evidence_ids=["EVID_A"]
            )
        ],
        claim_ledger=ClaimLedger(claims=[claim()]),
        keyword_coverage=KeywordCoverageReport(),
    )


def review(document, status=VerificationStatus.SUPPORTED):
    return ClaimReviewSet(
        draft_digest=draft_digest(document),
        evidence_digest=evidence_digest([evidence()]),
        reviews=[
            ClaimReview(
                claim_id="CLAIM_1",
                status=status,
                reason="Evidence explicitly states the same responsibility.",
            )
        ],
    )


def test_independent_reviewer_can_veto_generation_label():
    document = draft()
    assert not verify_draft(document, [evidence()], None).passed
    assert not verify_draft(
        document, [evidence()], review(document, VerificationStatus.UNSUPPORTED)
    ).passed
    assert verify_draft(document, [evidence()], review(document)).passed


def test_review_is_bound_to_current_draft_and_evidence():
    document = draft()
    verdict = review(document)
    document.items[0].text = "Managed an entire company."
    assert not verify_draft(document, [evidence()], verdict).passed
    document = draft()
    changed = evidence().model_copy(update={"statement": "Assisted a migration."})
    assert not verify_draft(document, [changed], verdict).passed


def test_ledger_must_cover_all_item_text_and_evidence():
    document = draft()
    document.items[0].text += " Delivered 900% growth."
    report = verify_draft(document, [evidence()], review(document))
    assert not report.passed
    assert "uncovered_item_text" in [i.code for i in report.issues]
    document = draft()
    document.items.append(document.items[0].model_copy(update={"id": "ITEM_2"}))
    assert not verify_draft(document, [evidence()], review(document)).passed


def test_missing_duplicate_or_foreign_review_is_rejected():
    document = draft()
    verdict = review(document)
    verdict.reviews = []
    assert not verify_draft(document, [evidence()], verdict).passed
    verdict.reviews = [review(document).reviews[0]] * 2
    assert not verify_draft(document, [evidence()], verdict).passed
