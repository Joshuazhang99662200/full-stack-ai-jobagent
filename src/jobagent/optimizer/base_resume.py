"""Project confirmed candidate evidence into the optimizer's input contract.

The candidate knowledge base stores evidence; the tailoring step consumes a
`BaseResumeDocument`. Nothing used to bridge the two, so every caller had to
hand-write that document and the link back to evidence was whatever the author
happened to type.

This is a projection, not authoring. Each item carries the statement of exactly
one confirmed evidence item, verbatim, so the base resume can never contain a
claim the candidate has not confirmed.
"""

import hashlib
from collections.abc import Sequence

from jobagent.errors import ContractValidationError
from jobagent.schemas.candidate import EvidenceItem, EvidenceType
from jobagent.schemas.optimizer import BaseResumeDocument, BaseResumeItem

_SECTION_BY_TYPE = {
    EvidenceType.EXPERIENCE: "experience",
    EvidenceType.MANAGEMENT: "experience",
    EvidenceType.COMMERCIAL: "experience",
    EvidenceType.DOMAIN: "experience",
    EvidenceType.PROJECT: "projects",
    EvidenceType.ACHIEVEMENT: "achievements",
    EvidenceType.SKILL: "skills",
    EvidenceType.EDUCATION: "education",
    EvidenceType.LANGUAGE: "languages",
    EvidenceType.CERTIFICATION: "certifications",
}
_EVIDENCE_PREFIX = "EVID_"
_ITEM_PREFIX = "ITEM_"


class BaseResumeBuilder:
    """Build the base resume the optimizer tailors from."""

    def build(
        self,
        *,
        candidate_id: str,
        evidence: Sequence[EvidenceItem],
        language: str,
    ) -> BaseResumeDocument:
        confirmed = [item for item in evidence if item.user_confirmed]
        if not confirmed:
            raise ContractValidationError(
                "A base resume needs confirmed evidence; none of the supplied evidence "
                "is confirmed.",
                details={"candidate_id": candidate_id, "supplied": len(evidence)},
            )

        items = [
            BaseResumeItem(
                id=self._item_id(item.id),
                section=_SECTION_BY_TYPE.get(item.type, "experience"),
                text=item.statement,
                evidence_ids=[item.id],
            )
            for item in confirmed
        ]
        return BaseResumeDocument(
            id=f"BASE_RESUME_{self._digest(candidate_id, items)[7:23].upper()}",
            language=language,
            items=items,
            source_digest=self._digest(candidate_id, items),
        )

    @staticmethod
    def _item_id(evidence_id: str) -> str:
        """Keep the evidence identity readable in the item it seeded."""
        if evidence_id.startswith(_EVIDENCE_PREFIX):
            return _ITEM_PREFIX + evidence_id[len(_EVIDENCE_PREFIX) :]
        return _ITEM_PREFIX + evidence_id

    @staticmethod
    def _digest(candidate_id: str, items: Sequence[BaseResumeItem]) -> str:
        """Identify exactly this projection, so a variant records what it grew from."""
        payload = "\n".join(
            [candidate_id, *(f"{item.id}\0{item.section}\0{item.text}" for item in items)]
        )
        return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
