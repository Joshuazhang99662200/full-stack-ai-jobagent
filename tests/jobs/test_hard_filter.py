from datetime import UTC, datetime

from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.common import MoneyRange
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    HardFilterPolicy,
    SourceJobRecord,
)
from jobagent.schemas.jobs import (
    FilterDecision,
    JobRequirement,
    JobRequirementProfile,
    RequirementPriority,
)


def job(*, title: str = "Python Engineer", location: str = "Copenhagen", salary: str | None = None):
    return JobNormalizer().normalize(
        SourceJobRecord(
            source="mock-alpha",
            source_job_id="alpha-001",
            title=title,
            company="Example Labs",
            location=location,
            salary_text=salary,
            jd_raw="Build Python services.",
            url="https://jobs.example.test/alpha-001",
            collected_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )


def requirements(job_id: str, *items: JobRequirement) -> JobRequirementProfile:
    return JobRequirementProfile(job_id=job_id, requirements=list(items))


def context(**updates: object) -> CandidateFilterContext:
    values: dict[str, object] = {"candidate_id": "CAND_001"}
    values.update(updates)
    return CandidateFilterContext(**values)


def test_filter_passes_when_no_hard_constraint_is_triggered() -> None:
    normalized = job()

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.PASS
    assert result.reasons == []


def test_explicit_role_exclusion_returns_reasoned_reject() -> None:
    normalized = job(title="Enterprise Sales Manager")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(excluded_role_terms=["sales"]),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REJECT
    assert [reason.rule_id for reason in result.reasons] == ["ROLE_EXCLUSION"]


def test_unknown_remote_and_compensation_data_remain_review() -> None:
    normalized = job(location="Remote - Europe")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(
            allowed_locations=["Copenhagen"],
            remote_allowed=None,
            minimum_compensation=MoneyRange(
                currency="DKK",
                minimum=600000,
                period="year",
            ),
        ),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REVIEW
    assert [reason.rule_id for reason in result.reasons] == [
        "LOCATION_HARD_CONSTRAINT",
        "COMPENSATION_MINIMUM",
    ]


def test_explicit_unmet_language_requirement_rejects() -> None:
    normalized = job()
    language = JobRequirement(
        id="REQ_LANGUAGE",
        statement="Professional Danish is required.",
        category="language",
        priority=RequirementPriority.MUST,
        source_span="Professional Danish is required.",
        keywords=["Danish"],
    )

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id, language),
        context(languages={"Danish": "none"}),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REJECT
    assert result.reasons[0].rule_id == "LANGUAGE_HARD_REQUIREMENT"


def test_multiple_reject_reasons_keep_catalog_order() -> None:
    normalized = job(title="Sales Manager", location="Berlin")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(allowed_locations=["Copenhagen"], excluded_role_terms=["sales"]),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REJECT
    assert [reason.rule_id for reason in result.reasons] == [
        "LOCATION_HARD_CONSTRAINT",
        "ROLE_EXCLUSION",
    ]
