"""Select confirmed evidence deterministically, retaining base-resume references."""

import re
from collections.abc import Sequence

from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.jobs import JobRequirementProfile
from jobagent.schemas.optimizer import BaseResumeDocument


def select_evidence(
    evidence: Sequence[EvidenceItem],
    requirements: JobRequirementProfile,
    base: BaseResumeDocument,
) -> tuple[list[EvidenceItem], list[str]]:
    mandatory = {e for item in base.items for e in item.evidence_ids}
    terms = set(
        re.findall(
            r"[\w]+",
            " ".join(
                [
                    *requirements.skills,
                    *requirements.domains,
                    *(k for r in requirements.requirements for k in r.keywords),
                ]
            ).casefold(),
        )
    )
    selected = []
    omitted = []
    for item in sorted(evidence, key=lambda e: e.id):
        if not item.user_confirmed:
            continue
        tokens = set(
            re.findall(r"[\w]+", " ".join([item.statement, *item.skills, *item.domains]).casefold())
        )
        if item.id in mandatory or bool(tokens & terms):
            selected.append(item)
        else:
            omitted.append(item.id)
    return selected, omitted
