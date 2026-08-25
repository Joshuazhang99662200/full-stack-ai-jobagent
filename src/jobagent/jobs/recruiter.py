"""Deterministically classify who is recruiting, and how sure we are.

Recruiter type is **inferred**, not observed, so it is the first attribute in this
project allowed to influence an artifact without being evidence-backed. It is
therefore reported with a confidence and the exact signals that produced it, and
routing gates on the confidence rather than trusting the label.

Everything here is rule-based on purpose: a routing decision has to be
reproducible and explainable after the fact.
"""

from collections.abc import Sequence

from jobagent.schemas.jobs import RecruiterInfo, RecruiterType

# Ordered strongest-first. The first rule that fires wins.
# Only the platform's own standalone label counts as stated. An agency-sounding
# company name is an inference and must not borrow the stated tier's confidence.
_HEADHUNTER_MARKERS = ("猎头", "headhunter")
_AGENCY_NAME_MARKERS = ("人才", "咨询", "猎头", "顾问", "consulting", "search")
_HR_MARKERS = ("hr", "人力资源", "人事", "招聘专员", "招聘经理", "hrbp", "talent acquisition")
_MANAGER_MARKERS = ("总监", "经理", "负责人", "主管", "总经理", "cto", "cio", "vp", "leader")

# Confidences are ordinal, not probabilities: they rank how directly the platform
# stated the fact, so a threshold can separate "stated" from "deduced".
_STATED = 0.95
_TITLE_INFERRED = 0.8
_NAME_INFERRED = 0.6
_ORG_MATCH = 0.6

DEFAULT_ROUTING_THRESHOLD = 0.8


def _contains(haystack: str, markers: Sequence[str]) -> str | None:
    lowered = haystack.casefold()
    for marker in markers:
        if marker.casefold() in lowered:
            return marker
    return None


def _same_company(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.strip().casefold() == right.strip().casefold()


class RecruiterClassifier:
    """Turn observed recruiter fields into a typed, explainable classification."""

    def classify(
        self,
        *,
        name: str | None = None,
        title: str | None = None,
        organization: str | None = None,
        hiring_company: str | None = None,
        job_kind: str | None = None,
    ) -> RecruiterInfo:
        surface = " ".join(part for part in (title, organization) if part)
        signals: list[str] = []

        stated = _contains(surface, _HEADHUNTER_MARKERS)
        if stated is not None:
            signals.append(f"platform_label:{stated}")
            if job_kind is not None:
                signals.append(f"job_kind:{job_kind}")
            return self._info(
                name, title, organization, RecruiterType.HEADHUNTER, _STATED, signals
            )

        hr_marker = _contains(surface, _HR_MARKERS)
        if hr_marker is not None:
            signals.append(f"title_marker:{hr_marker}")
            return self._info(name, title, organization, RecruiterType.HR, _TITLE_INFERRED, signals)

        manager_marker = _contains(surface, _MANAGER_MARKERS)
        if manager_marker is not None:
            signals.append(f"title_marker:{manager_marker}")
            return self._info(
                name, title, organization, RecruiterType.HIRING_MANAGER, _TITLE_INFERRED, signals
            )

        if _same_company(organization, hiring_company):
            # Employer-side is proven; HR versus hiring manager is not. Say so.
            signals.append("organization_matches_hiring_company")
            return self._info(
                name,
                title,
                organization,
                RecruiterType.INTERNAL_UNSPECIFIED,
                _ORG_MATCH,
                signals,
            )

        if organization and hiring_company:
            agency_marker = _contains(organization, _AGENCY_NAME_MARKERS)
            signals.append("organization_differs_from_hiring_company")
            if agency_marker is not None:
                signals.append(f"agency_name_marker:{agency_marker}")
            return self._info(
                name, title, organization, RecruiterType.HEADHUNTER, _NAME_INFERRED, signals
            )

        return self._info(name, title, organization, RecruiterType.UNKNOWN, 0.0, signals)

    @staticmethod
    def _info(
        name: str | None,
        title: str | None,
        organization: str | None,
        recruiter_type: RecruiterType,
        confidence: float,
        signals: list[str],
    ) -> RecruiterInfo:
        return RecruiterInfo(
            name=name,
            title=title,
            organization=organization,
            type=recruiter_type,
            type_confidence=confidence,
            type_signals=signals,
        )


def is_routable(recruiter: RecruiterInfo, threshold: float = DEFAULT_ROUTING_THRESHOLD) -> bool:
    """Whether a rewrite strategy may be selected on this classification.

    Below the threshold the caller falls back to the general strategy. It does not
    guess, and it does not quietly downgrade the threshold.
    """
    return (
        recruiter.type is not RecruiterType.UNKNOWN and recruiter.type_confidence >= threshold
    )
