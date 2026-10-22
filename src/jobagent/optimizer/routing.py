"""Select the rewrite lens from what earlier stages actually observed.

This router is part of the skill, not configuration. It is deliberately not
pluggable: a lens decides what a resume variant emphasises, so an externally
supplied lens could quietly sidestep the evidence contract and the quality gates.
Sources are data; routing is the skill's own judgement.

The decision is rule-based and reports its signals, because a routing choice has
to be reproducible and explainable after the fact.

Every lens draws on the *same* confirmed evidence. A lens may reorder, re-weight
and re-word; it may never introduce a fact, and it may never change one.
"""

from jobagent.jobs.recruiter import is_routable
from jobagent.schemas.jobs import RecruiterInfo, RecruiterType
from jobagent.schemas.optimizer import LensSelection as LensSelection
from jobagent.schemas.optimizer import RewriteLens as RewriteLens

# Each lens loads exactly one L2 policy body. Progressive loading means the
# router must name the resource, not inline its content.
LENS_POLICIES: dict[RewriteLens, str] = {
    RewriteLens.HEADHUNTER: "references/optimizer/lens-headhunter.md",
    RewriteLens.INTERNAL_HR: "references/optimizer/lens-internal-hr.md",
    RewriteLens.HIRING_MANAGER: "references/optimizer/lens-hiring-manager.md",
    RewriteLens.GENERAL: "references/optimizer/lens-general.md",
}

_BY_RECRUITER_TYPE = {
    RecruiterType.HEADHUNTER: RewriteLens.HEADHUNTER,
    RecruiterType.HR: RewriteLens.INTERNAL_HR,
    RecruiterType.HIRING_MANAGER: RewriteLens.HIRING_MANAGER,
}


class RewriteLensRouter:
    """Map observed recruiter identity onto a rewrite lens, or fall back."""

    def select(self, recruiter: RecruiterInfo | None = None) -> LensSelection:
        if recruiter is None:
            return self._general("No recruiter was observed for this posting.", [])

        candidate = _BY_RECRUITER_TYPE.get(recruiter.type)
        signals = list(recruiter.type_signals)

        if candidate is None:
            # INTERNAL_UNSPECIFIED and UNKNOWN are honest non-answers, not
            # near-misses: nothing here distinguishes HR from a hiring manager.
            return self._general(
                f"Recruiter type '{recruiter.type.value}' does not identify a lens.",
                signals,
            )

        if not is_routable(recruiter):
            return LensSelection(
                lens=RewriteLens.GENERAL,
                policy_path=LENS_POLICIES[RewriteLens.GENERAL],
                reason=(
                    f"Recruiter looked like '{recruiter.type.value}' but confidence "
                    f"{recruiter.type_confidence} is below the routing threshold."
                ),
                signals=signals,
                declined_lens=candidate,
            )

        return LensSelection(
            lens=candidate,
            policy_path=LENS_POLICIES[candidate],
            reason=f"Recruiter is classified '{recruiter.type.value}' with sufficient confidence.",
            signals=signals,
        )

    @staticmethod
    def _general(reason: str, signals: list[str]) -> LensSelection:
        return LensSelection(
            lens=RewriteLens.GENERAL,
            policy_path=LENS_POLICIES[RewriteLens.GENERAL],
            reason=reason,
            signals=signals,
        )
