"""Deterministic candidate/job hard-filter rules."""

from collections.abc import Callable

from jobagent.errors import ContractValidationError
from jobagent.schemas.job_intelligence import CandidateFilterContext, HardFilterPolicy
from jobagent.schemas.jobs import (
    FilterDecision,
    FilterReason,
    HardFilterResult,
    JobRequirementProfile,
    NormalizedJob,
    RequirementPriority,
)

_RULE_ORDER = (
    "LOCATION_HARD_CONSTRAINT",
    "WORK_AUTHORIZATION",
    "LANGUAGE_HARD_REQUIREMENT",
    "EDUCATION_HARD_REQUIREMENT",
    "COMPENSATION_MINIMUM",
    "ROLE_EXCLUSION",
)
_SEVERITY = {
    FilterDecision.PASS: 0,
    FilterDecision.REVIEW: 1,
    FilterDecision.REJECT: 2,
}
RuleResult = tuple[FilterDecision, FilterReason] | None


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


class HardFilterEngine:
    """Evaluate pure, explainable hard constraints in catalog order."""

    def evaluate(
        self,
        job: NormalizedJob,
        requirements: JobRequirementProfile,
        context: CandidateFilterContext,
        policy: HardFilterPolicy,
    ) -> HardFilterResult:
        if requirements.job_id != job.id:
            raise ContractValidationError(
                "Hard-filter requirements belong to another job.",
                details={"job_id": job.id, "requirements_job_id": requirements.job_id},
            )
        rule_functions: dict[str, Callable[[], RuleResult]] = {
            "LOCATION_HARD_CONSTRAINT": lambda: self._location(job, context, policy),
            "WORK_AUTHORIZATION": lambda: self._work_authorization(
                job, requirements, context, policy
            ),
            "LANGUAGE_HARD_REQUIREMENT": lambda: self._language(requirements, context, policy),
            "EDUCATION_HARD_REQUIREMENT": lambda: self._education(requirements, context, policy),
            "COMPENSATION_MINIMUM": lambda: self._compensation(job, context, policy),
            "ROLE_EXCLUSION": lambda: self._role_exclusion(job, context),
        }
        enabled = set(policy.enabled_rule_ids)
        triggered = [
            result
            for rule_id in _RULE_ORDER
            if rule_id in enabled
            if (result := rule_functions[rule_id]()) is not None
        ]
        if not triggered:
            return HardFilterResult(decision=FilterDecision.PASS)
        decision = max((item[0] for item in triggered), key=_SEVERITY.__getitem__)
        return HardFilterResult(
            decision=decision,
            reasons=[item[1] for item in triggered],
        )

    @staticmethod
    def _location(
        job: NormalizedJob,
        context: CandidateFilterContext,
        policy: HardFilterPolicy,
    ) -> RuleResult:
        if not context.allowed_locations:
            return None
        observed = _normalized(job.location)
        allowed = {_normalized(value) for value in context.allowed_locations}
        if observed in allowed:
            return None
        if "remote" in observed:
            if context.remote_allowed is True:
                return None
            if context.remote_allowed is None and policy.review_on_unknown:
                return (
                    FilterDecision.REVIEW,
                    FilterReason(
                        rule_id="LOCATION_HARD_CONSTRAINT",
                        message="Remote-location compatibility requires review.",
                        observed_value=job.location,
                        required_value=", ".join(context.allowed_locations),
                    ),
                )
        return (
            FilterDecision.REJECT,
            FilterReason(
                rule_id="LOCATION_HARD_CONSTRAINT",
                message="Job location conflicts with the candidate hard constraint.",
                observed_value=job.location,
                required_value=", ".join(context.allowed_locations),
            ),
        )

    @staticmethod
    def _work_authorization(
        job: NormalizedJob,
        requirements: JobRequirementProfile,
        context: CandidateFilterContext,
        policy: HardFilterPolicy,
    ) -> RuleResult:
        required = [
            item
            for item in requirements.requirements
            if item.priority is RequirementPriority.MUST
            and _normalized(item.category) in {"work authorization", "work_authorization"}
        ]
        if not required:
            return None
        if not context.work_authorized_locations:
            if not policy.review_on_unknown:
                return None
            return (
                FilterDecision.REVIEW,
                FilterReason(
                    rule_id="WORK_AUTHORIZATION",
                    message="Candidate work authorization is unknown.",
                    observed_value=None,
                    required_value=required[0].statement,
                ),
            )
        authorized = {_normalized(value) for value in context.work_authorized_locations}
        if _normalized(job.location) in authorized:
            return None
        return (
            FilterDecision.REJECT,
            FilterReason(
                rule_id="WORK_AUTHORIZATION",
                message="Candidate authorization does not cover the job location.",
                observed_value=", ".join(context.work_authorized_locations),
                required_value=job.location,
            ),
        )

    @staticmethod
    def _language(
        requirements: JobRequirementProfile,
        context: CandidateFilterContext,
        policy: HardFilterPolicy,
    ) -> RuleResult:
        candidate_languages = {
            _normalized(name): _normalized(level) for name, level in context.languages.items()
        }
        for item in requirements.requirements:
            if (
                item.priority is not RequirementPriority.MUST
                or _normalized(item.category) != "language"
            ):
                continue
            language = item.keywords[0] if item.keywords else item.statement
            level = candidate_languages.get(_normalized(language))
            if level is None:
                if not policy.review_on_unknown:
                    continue
                return (
                    FilterDecision.REVIEW,
                    FilterReason(
                        rule_id="LANGUAGE_HARD_REQUIREMENT",
                        message="Candidate language proficiency is unknown.",
                        required_value=item.statement,
                    ),
                )
            if level in {"none", "no", "not available"}:
                return (
                    FilterDecision.REJECT,
                    FilterReason(
                        rule_id="LANGUAGE_HARD_REQUIREMENT",
                        message="Candidate explicitly lacks a required language.",
                        observed_value=level,
                        required_value=item.statement,
                    ),
                )
        return None

    @staticmethod
    def _education(
        requirements: JobRequirementProfile,
        context: CandidateFilterContext,
        policy: HardFilterPolicy,
    ) -> RuleResult:
        required = [
            item
            for item in requirements.requirements
            if item.priority is RequirementPriority.MUST
            and _normalized(item.category) == "education"
        ]
        if not required:
            return None
        if not context.education_levels:
            if not policy.review_on_unknown:
                return None
            return (
                FilterDecision.REVIEW,
                FilterReason(
                    rule_id="EDUCATION_HARD_REQUIREMENT",
                    message="Candidate education equivalence is unknown.",
                    required_value=required[0].statement,
                ),
            )
        available = " ".join(_normalized(value) for value in context.education_levels)
        if any(
            any(_normalized(keyword) in available for keyword in item.keywords) for item in required
        ):
            return None
        return (
            FilterDecision.REJECT,
            FilterReason(
                rule_id="EDUCATION_HARD_REQUIREMENT",
                message="Candidate education does not meet the explicit hard requirement.",
                observed_value=", ".join(context.education_levels),
                required_value=required[0].statement,
            ),
        )

    @staticmethod
    def _compensation(
        job: NormalizedJob,
        context: CandidateFilterContext,
        policy: HardFilterPolicy,
    ) -> RuleResult:
        minimum = context.minimum_compensation
        if minimum is None:
            return None
        if job.salary is None:
            if not policy.review_on_unknown:
                return None
            return (
                FilterDecision.REVIEW,
                FilterReason(
                    rule_id="COMPENSATION_MINIMUM",
                    message="Job compensation is unavailable.",
                    required_value=minimum.model_dump_json(),
                ),
            )
        if job.salary.currency != minimum.currency or job.salary.period != minimum.period:
            return (
                FilterDecision.REVIEW,
                FilterReason(
                    rule_id="COMPENSATION_MINIMUM",
                    message="Job compensation currency or period is not directly comparable.",
                    observed_value=job.salary.model_dump_json(),
                    required_value=minimum.model_dump_json(),
                ),
            )
        if (
            minimum.minimum is not None
            and job.salary.maximum is not None
            and job.salary.maximum < minimum.minimum
        ):
            return (
                FilterDecision.REJECT,
                FilterReason(
                    rule_id="COMPENSATION_MINIMUM",
                    message="Job maximum compensation is below the candidate minimum.",
                    observed_value=str(job.salary.maximum),
                    required_value=str(minimum.minimum),
                ),
            )
        return None

    @staticmethod
    def _role_exclusion(job: NormalizedJob, context: CandidateFilterContext) -> RuleResult:
        title = _normalized(job.title)
        matched = next(
            (term for term in context.excluded_role_terms if _normalized(term) in title),
            None,
        )
        if matched is None:
            return None
        return (
            FilterDecision.REJECT,
            FilterReason(
                rule_id="ROLE_EXCLUSION",
                message="Job title matches a candidate role exclusion.",
                observed_value=job.title,
                required_value=f"exclude: {matched}",
            ),
        )
