"""Turn a claim ledger into a verdict, deterministically.

The reasoning step judges whether each claim is entailed by the evidence it
cites. This module decides whether the variant may ship. That split matters: a
model must never be able to declare its own draft passing, because fluent prose
is exactly what a verifier is supposed to be able to veto.

On top of aggregating the model's own per-claim judgements, this module
independently re-checks every metric against the cited evidence. A fabricated
number therefore fails even when the claim carrying it was labelled supported.
"""

from collections.abc import Iterable, Mapping

from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.optimizer import (
    ClaimLedger,
    ClaimRecord,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)

UNSUPPORTED_CLAIM = "unsupported_claim"
CONTRADICTED_CLAIM = "contradicted_claim"
NARROWING_REQUIRED = "narrowing_required"
UNSUPPORTED_METRIC = "unsupported_metric"
UNKNOWN_EVIDENCE = "unknown_evidence"
UNCONFIRMED_EVIDENCE = "unconfirmed_evidence"


def _metric_key(name: str, value: object, unit: str) -> tuple[str, str, str]:
    return (name.strip().casefold(), str(value), unit.strip().casefold())


class ClaimVerifier:
    """Aggregate per-claim judgements into a shippable-or-not verdict."""

    def verify(
        self,
        ledger: ClaimLedger,
        evidence: Iterable[EvidenceItem],
    ) -> VerificationReport:
        by_id: Mapping[str, EvidenceItem] = {item.id: item for item in evidence}
        issues: list[VerificationIssue] = []

        unsupported = 0
        contradicted = 0
        exaggerations = 0
        unsupported_metrics = 0
        supported = 0

        for claim in ledger.claims:
            issues.extend(self._evidence_issues(claim, by_id))
            unsupported_metrics += len(self._metric_issues(claim, by_id, issues))

            if claim.verification_status is VerificationStatus.SUPPORTED:
                supported += 1
            elif claim.verification_status is VerificationStatus.UNSUPPORTED:
                unsupported += 1
                issues.append(
                    VerificationIssue(
                        code=UNSUPPORTED_CLAIM,
                        message="Claim is not supported by the evidence it cites.",
                        claim_id=claim.claim_id,
                        resume_item_id=claim.resume_item_id,
                    )
                )
            elif claim.verification_status is VerificationStatus.CONTRADICTED:
                contradicted += 1
                issues.append(
                    VerificationIssue(
                        code=CONTRADICTED_CLAIM,
                        message="Claim is contradicted by the evidence it cites.",
                        claim_id=claim.claim_id,
                        resume_item_id=claim.resume_item_id,
                    )
                )
            else:
                # Partially supported means the wording reaches past the evidence.
                # That is semantic overreach: narrow it and verify again.
                exaggerations += 1
                issues.append(
                    VerificationIssue(
                        code=NARROWING_REQUIRED,
                        message=(
                            "Claim reaches beyond its evidence; "
                            "narrow the wording and verify again."
                        ),
                        claim_id=claim.claim_id,
                        resume_item_id=claim.resume_item_id,
                    )
                )

        total = len(ledger.claims)
        coverage = 1.0 if total == 0 else supported / total
        blocking = bool(unsupported or contradicted or unsupported_metrics or exaggerations)
        return VerificationReport(
            passed=not blocking and coverage == 1.0 and not issues,
            unsupported_claims=unsupported,
            contradicted_claims=contradicted,
            unsupported_metrics=unsupported_metrics,
            semantic_exaggerations=exaggerations,
            evidence_coverage=coverage,
            issues=issues,
        )

    @staticmethod
    def _evidence_issues(
        claim: ClaimRecord, by_id: Mapping[str, EvidenceItem]
    ) -> list[VerificationIssue]:
        issues: list[VerificationIssue] = []
        for evidence_id in claim.evidence_ids:
            item = by_id.get(evidence_id)
            if item is None:
                issues.append(
                    VerificationIssue(
                        code=UNKNOWN_EVIDENCE,
                        message=f"Claim cites evidence {evidence_id}, which does not exist.",
                        claim_id=claim.claim_id,
                        resume_item_id=claim.resume_item_id,
                    )
                )
            elif not item.user_confirmed:
                # Only canonical evidence may reach a final variant.
                issues.append(
                    VerificationIssue(
                        code=UNCONFIRMED_EVIDENCE,
                        message=f"Claim cites unconfirmed evidence {evidence_id}.",
                        claim_id=claim.claim_id,
                        resume_item_id=claim.resume_item_id,
                    )
                )
        return issues

    @staticmethod
    def _metric_issues(
        claim: ClaimRecord,
        by_id: Mapping[str, EvidenceItem],
        issues: list[VerificationIssue],
    ) -> list[VerificationIssue]:
        """Re-derive every metric from evidence rather than trusting the label."""
        available = {
            _metric_key(metric.name, metric.value, metric.unit)
            for evidence_id in claim.evidence_ids
            if (item := by_id.get(evidence_id)) is not None
            for metric in item.metrics
        }
        found: list[VerificationIssue] = []
        for metric in claim.metric_facts:
            if _metric_key(metric.name, metric.value, metric.unit) not in available:
                issue = VerificationIssue(
                    code=UNSUPPORTED_METRIC,
                    message=(
                        f"Metric '{metric.name}' = {metric.value}{metric.unit} does not appear "
                        "in the cited evidence."
                    ),
                    claim_id=claim.claim_id,
                    resume_item_id=claim.resume_item_id,
                )
                found.append(issue)
                issues.append(issue)
        return found
