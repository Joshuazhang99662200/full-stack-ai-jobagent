"""Assemble a JD-targeted resume variant from confirmed evidence.

Splits along the line that matters:

- The reasoning step rewrites items and judges, per claim, whether the evidence
  it cites entails it. That is the part that needs judgement.
- This module decides whether the result ships, builds the diff, and assembles
  the variant. That is the part that must not be talkable-around.

The rewrite lens chosen by the router is passed through as context. A lens shifts
emphasis, ordering and wording; it never licenses a new fact, so it cannot relax
anything enforced here.
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

from jobagent.capabilities import ReasoningProvider
from jobagent.errors import ContractValidationError
from jobagent.optimizer.diffing import ResumeDiffBuilder
from jobagent.optimizer.routing import LensSelection
from jobagent.optimizer.verification import ClaimVerifier
from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.common import ContractModel
from jobagent.schemas.jobs import JobRequirementProfile
from jobagent.schemas.optimizer import (
    BaseResumeDocument,
    ClaimLedger,
    KeywordCoverageReport,
    OptimizedResumeItem,
    ResumeVariant,
)
from jobagent.skill_resources import read_reference

PROMPT_ID = "resume.tailor.v1"


class TailoredDraft(ContractModel):
    """What the reasoning step returns: rewritten items plus their claim ledger."""

    items: list[OptimizedResumeItem]
    claim_ledger: ClaimLedger
    keyword_coverage: KeywordCoverageReport


class ResumeTailor:
    """Produce a verified `ResumeVariant`, or a failing one that cannot ship."""

    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def tailor(
        self,
        *,
        base_resume: BaseResumeDocument,
        requirements: JobRequirementProfile,
        evidence: Sequence[EvidenceItem],
        lens: LensSelection,
        target_role: str,
        variant_id: str,
    ) -> ResumeVariant:
        confirmed = [item for item in evidence if item.user_confirmed]
        if not confirmed:
            raise ContractValidationError(
                "Tailoring needs confirmed evidence; none of the supplied evidence is confirmed.",
                details={"supplied": len(evidence)},
            )

        lens_body = read_reference(lens.policy_path)
        context = {
            "target_role": target_role,
            "lens": lens.lens.value,
            "lens_policy": lens_body,
            "lens_reason": lens.reason,
            "requirements": requirements.model_dump(mode="json"),
            "base_resume": base_resume.model_dump(mode="json"),
            "confirmed_evidence": [item.model_dump(mode="json") for item in confirmed],
        }
        draft = self.provider.generate(
            prompt_id=PROMPT_ID,
            context=context,
            output_type=TailoredDraft,
        )

        verification = ClaimVerifier().verify(draft.claim_ledger, confirmed)
        diff = ResumeDiffBuilder().build(base_resume.items, draft.items)
        return ResumeVariant(
            id=variant_id,
            target_job_id=requirements.job_id,
            target_role=target_role,
            selected_evidence_ids=sorted(
                {item for claim in draft.claim_ledger.claims for item in claim.evidence_ids}
            ),
            items=list(draft.items),
            claim_ledger=draft.claim_ledger,
            keyword_coverage=draft.keyword_coverage,
            verification=verification,
            diff=diff,
            prompt_bundle_digest=_digest(lens_body, base_resume.source_digest),
            generated_at=datetime.now(UTC),
        )


def _digest(lens_body: str, source_digest: str) -> str:
    """Bind a variant to the exact lens text and base resume that produced it."""
    payload = f"{PROMPT_ID}\n{source_digest}\n{lens_body}".encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
