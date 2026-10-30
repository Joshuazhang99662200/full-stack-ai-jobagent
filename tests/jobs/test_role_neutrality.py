"""Public hard filters are candidate-configured across occupational families."""

from datetime import UTC, datetime

import pytest

from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    HardFilterPolicy,
    SourceJobRecord,
)
from jobagent.schemas.jobs import FilterDecision, JobRequirementProfile


@pytest.mark.parametrize(
    "title,duties",
    [
        ("Software Engineer", "Build distributed services and monitor production reliability."),
        ("Research Associate", "Design reproducible experiments and analyze research results."),
        ("Visual Designer", "Design visual systems and test accessible interaction patterns."),
        ("Financial Analyst", "Analyze cash flows and assess financial reporting quality."),
        ("Operations Manager", "Improve operational processes and measure service quality."),
        ("Sales Representative", "Qualify customer requirements and maintain sales forecasts."),
        ("Research Intern", "Assist research experiments and document analysis methods."),
        ("Product Manager", "Research user needs and prioritize product outcomes."),
    ],
)
def test_role_families_have_no_implicit_product_only_filter(title, duties):
    job = JobNormalizer().normalize(
        SourceJobRecord(
            source="mock",
            source_job_id="SYNTHETIC_ROLE",
            title=title,
            company="Example Organization",
            location="Example City",
            jd_raw=duties,
            url="https://jobs.example.test/synthetic-role",
            collected_at=datetime(2026, 10, 30, tzinfo=UTC),
        )
    )
    requirements = JobRequirementProfile(job_id=job.id)
    engine = HardFilterEngine()

    default = engine.evaluate(
        job, requirements, CandidateFilterContext(candidate_id="CAND_DEMO"), HardFilterPolicy(),
    )
    explicit = engine.evaluate(
        job, requirements,
        CandidateFilterContext(candidate_id="CAND_DEMO", excluded_role_terms=[title]),
        HardFilterPolicy(),
    )

    assert default.decision is FilterDecision.PASS
    assert explicit.decision is FilterDecision.REJECT
    assert explicit.reasons[0].rule_id == "ROLE_EXCLUSION"
