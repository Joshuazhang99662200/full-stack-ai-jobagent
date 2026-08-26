"""Build the human-readable diff between a base resume and a tailored variant.

Derived mechanically from the two documents, never narrated by the reasoning
step: a diff exists so a person can audit what changed, and a self-reported diff
would be able to omit the very edit worth reviewing.

Every substantive change is recorded, including omissions — a dropped bullet is
a change a reviewer has to see.
"""

from collections.abc import Iterable, Sequence

from jobagent.schemas.optimizer import (
    BaseResumeItem,
    OptimizedResumeItem,
    ResumeDiff,
    ResumeDiffItem,
    RewriteOperation,
)


class ResumeDiffBuilder:
    """Pair base and optimized items by ID and describe what changed."""

    def build(
        self,
        base_items: Sequence[BaseResumeItem],
        optimized_items: Sequence[OptimizedResumeItem],
    ) -> ResumeDiff:
        base_by_id = {item.id: item for item in base_items}
        seen: set[str] = set()
        entries: list[ResumeDiffItem] = []

        for optimized in optimized_items:
            source_ids = optimized.source_resume_item_ids or (
                [optimized.id] if optimized.id in base_by_id else []
            )
            seen.update(source_ids)
            originals = [base_by_id[item].text for item in source_ids if item in base_by_id]
            original = "\n".join(originals) if originals else None

            if original == optimized.text:
                continue
            entries.append(
                ResumeDiffItem(
                    original=original,
                    optimized=optimized.text,
                    reason=self._reason(original, optimized),
                    requirement_ids=list(optimized.requirement_ids),
                    evidence_ids=list(optimized.evidence_ids),
                    rewrite_operations=list(optimized.rewrite_operations),
                    risk_notes=list(self._risk_notes(original, optimized)),
                )
            )

        entries.extend(self._omissions(base_items, seen))
        return ResumeDiff(items=entries)

    @staticmethod
    def _reason(original: str | None, optimized: OptimizedResumeItem) -> str:
        if original is None:
            return "New item assembled from confirmed evidence."
        if optimized.rewrite_operations:
            applied = ", ".join(
                sorted(operation.value for operation in optimized.rewrite_operations)
            )
            return f"Rewritten with: {applied}."
        return "Rewritten without a declared operation."

    @staticmethod
    def _risk_notes(original: str | None, optimized: OptimizedResumeItem) -> list[str]:
        notes: list[str] = []
        if not optimized.rewrite_operations:
            # The operation vocabulary is closed; an undeclared edit cannot be audited.
            notes.append("No rewrite operation declared for a changed item.")
        if original is not None and len(optimized.text) > len(original) * 1.5:
            # Growth is where unevidenced detail tends to appear.
            notes.append("Optimized text is substantially longer than its source.")
        if not optimized.requirement_ids:
            notes.append("Item is not tied to any job requirement.")
        return notes

    @staticmethod
    def _omissions(
        base_items: Iterable[BaseResumeItem], seen: set[str]
    ) -> list[ResumeDiffItem]:
        return [
            ResumeDiffItem(
                original=item.text,
                optimized=None,
                reason="Omitted from this variant.",
                evidence_ids=list(item.evidence_ids),
                rewrite_operations=[RewriteOperation.OMIT],
                risk_notes=["Dropped content is not visible in the variant; confirm intent."],
            )
            for item in base_items
            if item.id not in seen
        ]
