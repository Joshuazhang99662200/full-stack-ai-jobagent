from datetime import UTC, datetime

import pytest

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


@pytest.mark.parametrize(
    ("available", "keyword", "expected"),
    [
        ("本科", "本科及以上学历", FilterDecision.PASS),
        ("硕士", "硕士及以上", FilterDecision.PASS),
        ("本科", "硕士及以上", FilterDecision.REJECT),
        ("专科", "本科及以上学历", FilterDecision.REJECT),
        ("本科", "计算机相关专业", FilterDecision.REJECT),
        ("本科", "本科及以上(计算机专业)", FilterDecision.REJECT),
    ],
)
def test_chinese_degree_qualifiers_do_not_reject_the_same_confirmed_degree(
    available: str, keyword: str, expected: FilterDecision
) -> None:
    normalized = job()
    education = JobRequirement(
        id="REQ_EDUCATION",
        statement=keyword,
        category="education",
        priority=RequirementPriority.MUST,
        source_span=keyword,
        keywords=[keyword],
    )

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id, education),
        context(education_levels=[available]),
        HardFilterPolicy(),
    )

    assert result.decision is expected
    assert education.keywords == [keyword]


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


def test_city_constraint_accepts_a_district_scoped_posting() -> None:
    """Boards publish `城市-区`; a candidate who accepts the city accepts its districts."""
    normalized = job(location="上海-浦东新区")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(allowed_locations=["上海"]),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.PASS
    assert result.reasons == []


@pytest.mark.parametrize(
    ("observed", "allowed", "expected"),
    [
        ("上海 浦东 张江", "上海", FilterDecision.PASS),
        ("上海\u3000浦东\u3000张江", "上海", FilterDecision.PASS),
        ("上海-浦东-张江", "上海 浦东", FilterDecision.PASS),
        ("上海", "上海 浦东", FilterDecision.REVIEW),
        ("北京 朝阳 望京", "上海", FilterDecision.REJECT),
        ("上海 浦东 张江", "海", FilterDecision.REJECT),
        ("New York", "New", FilterDecision.REJECT),
        ("上海 浦东 张江", "", FilterDecision.REJECT),
    ],
)
def test_chinese_location_spacing_preserves_city_and_district_constraints(
    observed: str, allowed: str, expected: FilterDecision
) -> None:
    normalized = job(location=observed)

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(allowed_locations=[allowed]),
        HardFilterPolicy(),
    )

    assert result.decision is expected
    assert normalized.location == " ".join(observed.split())


def test_district_constraint_reviews_a_city_scoped_posting() -> None:
    """A city-wide posting may or may not sit in the district the candidate named."""
    normalized = job(location="上海")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(allowed_locations=["上海-浦东新区"]),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REVIEW
    assert result.reasons[0].rule_id == "LOCATION_HARD_CONSTRAINT"


def test_a_different_city_still_rejects() -> None:
    normalized = job(location="北京-朝阳区")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(allowed_locations=["上海"]),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REJECT
    assert result.reasons[0].rule_id == "LOCATION_HARD_CONSTRAINT"


def test_location_segments_never_match_on_a_bare_substring() -> None:
    """`海` is a substring of `上海` but is not one of its segments."""
    normalized = job(location="上海-浦东新区")

    result = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(allowed_locations=["海"]),
        HardFilterPolicy(),
    )

    assert result.decision is FilterDecision.REJECT


def test_an_unstated_salary_counts_as_meeting_the_floor_when_the_person_says_so() -> None:
    normalized = job(salary="面议")
    floor = MoneyRange(currency="DKK", minimum=600000, period="year")

    default = HardFilterEngine().evaluate(
        normalized, requirements(normalized.id), context(minimum_compensation=floor),
        HardFilterPolicy(),
    )
    accepted = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(minimum_compensation=floor, unstated_compensation_passes=True),
        HardFilterPolicy(),
    )

    assert default.decision is FilterDecision.REVIEW
    assert accepted.decision is FilterDecision.PASS


def test_an_exception_phrase_keeps_a_product_role_past_an_excluded_term() -> None:
    normalized = job(title="AI投顾专家")

    blocked = HardFilterEngine().evaluate(
        normalized, requirements(normalized.id), context(excluded_role_terms=["投顾"]),
        HardFilterPolicy(),
    )
    allowed = HardFilterEngine().evaluate(
        normalized,
        requirements(normalized.id),
        context(excluded_role_terms=["投顾"], excluded_role_exceptions=["AI投顾"]),
        HardFilterPolicy(),
    )

    assert blocked.decision is FilterDecision.REJECT
    assert allowed.decision is FilterDecision.PASS
