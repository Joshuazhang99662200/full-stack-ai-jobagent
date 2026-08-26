"""The verifier decides whether a variant ships. The model must not be able to."""

from decimal import Decimal

from jobagent.optimizer.verification import ClaimVerifier
from jobagent.schemas.candidate import Confidence, EvidenceItem, EvidenceType, MetricFact
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.schemas.optimizer import ClaimLedger, ClaimRecord, VerificationStatus


def evidence(
    evidence_id: str = "EVID_A",
    *,
    confirmed: bool = True,
    metrics: list[MetricFact] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.EXPERIENCE,
        statement="Led a platform migration.",
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_1:page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
        metrics=metrics or [],
    )


def claim(
    *,
    status: VerificationStatus = VerificationStatus.SUPPORTED,
    evidence_ids: list[str] | None = None,
    metrics: list[MetricFact] | None = None,
    claim_id: str = "CLAIM_1",
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        resume_item_id="ITEM_1",
        text="Led a platform migration.",
        claim_type="experience",
        evidence_ids=evidence_ids or ["EVID_A"],
        metric_facts=metrics or [],
        verification_status=status,
    )


def test_all_supported_claims_pass() -> None:
    report = ClaimVerifier().verify(ClaimLedger(claims=[claim()]), [evidence()])

    assert report.passed
    assert report.evidence_coverage == 1.0
    assert report.issues == []


def test_empty_ledger_passes_vacuously() -> None:
    assert ClaimVerifier().verify(ClaimLedger(), []).passed


def test_unsupported_claim_blocks_delivery() -> None:
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(status=VerificationStatus.UNSUPPORTED)]), [evidence()]
    )

    assert not report.passed
    assert report.unsupported_claims == 1
    assert [issue.code for issue in report.issues] == ["unsupported_claim"]


def test_contradicted_claim_blocks_delivery() -> None:
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(status=VerificationStatus.CONTRADICTED)]), [evidence()]
    )

    assert not report.passed
    assert report.contradicted_claims == 1


def test_partial_support_counts_as_semantic_overreach() -> None:
    """Wording that reaches past its evidence must be narrowed, not shipped."""
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(status=VerificationStatus.PARTIALLY_SUPPORTED)]), [evidence()]
    )

    assert not report.passed
    assert report.semantic_exaggerations == 1
    assert [issue.code for issue in report.issues] == ["narrowing_required"]


def test_metric_absent_from_evidence_fails_even_when_labelled_supported() -> None:
    """The verifier re-derives metrics rather than trusting the model's label."""
    invented = MetricFact(name="团队规模", value=Decimal("30"), unit="人")
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(metrics=[invented])]), [evidence()]
    )

    assert not report.passed
    assert report.unsupported_metrics == 1
    assert any(issue.code == "unsupported_metric" for issue in report.issues)


def test_metric_present_in_evidence_is_accepted() -> None:
    metric = MetricFact(name="团队规模", value=Decimal("30"), unit="人")
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(metrics=[metric])]), [evidence(metrics=[metric])]
    )

    assert report.passed
    assert report.unsupported_metrics == 0


def test_citing_unconfirmed_evidence_blocks_delivery() -> None:
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim()]), [evidence(confirmed=False)]
    )

    assert not report.passed
    assert any(issue.code == "unconfirmed_evidence" for issue in report.issues)


def test_citing_nonexistent_evidence_blocks_delivery() -> None:
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(evidence_ids=["EVID_GHOST"])]), [evidence()]
    )

    assert not report.passed
    assert any(issue.code == "unknown_evidence" for issue in report.issues)


def test_coverage_reflects_the_share_of_fully_supported_claims() -> None:
    ledger = ClaimLedger(
        claims=[
            claim(claim_id="CLAIM_1"),
            claim(claim_id="CLAIM_2", status=VerificationStatus.UNSUPPORTED),
        ]
    )

    report = ClaimVerifier().verify(ledger, [evidence()])

    assert report.evidence_coverage == 0.5
    assert not report.passed


def test_a_passing_report_cannot_be_constructed_with_open_issues() -> None:
    """Defence in depth: the contract itself refuses an inconsistent verdict."""
    report = ClaimVerifier().verify(
        ClaimLedger(claims=[claim(status=VerificationStatus.UNSUPPORTED)]), [evidence()]
    )
    assert not report.passed
    # VerificationReport's own validator forbids passed=True alongside failures.
    import pytest
    from pydantic import ValidationError

    from jobagent.schemas.optimizer import VerificationReport

    with pytest.raises(ValidationError):
        VerificationReport(passed=True, unsupported_claims=1, evidence_coverage=1.0)
