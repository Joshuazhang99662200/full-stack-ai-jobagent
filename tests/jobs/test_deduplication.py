from datetime import UTC, datetime, timedelta

from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.job_intelligence import DeduplicationPolicy, SourceJobRecord


def job(
    source: str,
    source_job_id: str,
    *,
    jd: str = "Build Python API services and maintain platform reliability.",
    salary: str | None = "DKK 600000-720000 year",
    collected_offset: int = 0,
) -> object:
    record = SourceJobRecord(
        source=source,
        source_job_id=source_job_id,
        title="Python Platform Engineer",
        company="Example Labs",
        location="Copenhagen",
        salary_text=salary,
        jd_raw=jd,
        url=f"https://jobs.example.test/{source}/{source_job_id}",
        published_at=datetime(2026, 8, 18, tzinfo=UTC) + timedelta(days=collected_offset),
        collected_at=datetime(2026, 8, 21, tzinfo=UTC) + timedelta(minutes=collected_offset),
    )
    return JobNormalizer().normalize(record)


def test_exact_duplicates_merge_and_preserve_all_provenance() -> None:
    first = job("mock-alpha", "alpha-001")
    second = job("mock-beta", "beta-991", collected_offset=1)

    result = JobDeduplicator().deduplicate([first, second], DeduplicationPolicy())

    assert len(result.jobs) == 1
    assert {(item.source, item.source_id) for item in result.jobs[0].provenance} == {
        ("mock-alpha", "alpha-001"),
        ("mock-beta", "beta-991"),
    }
    assert len(result.duplicate_groups) == 1
    assert set(result.duplicate_groups[0].member_job_ids) == {first.id, second.id}


def test_near_duplicates_merge_only_above_threshold() -> None:
    first = job("mock-alpha", "alpha-001")
    near = job(
        "mock-beta",
        "beta-991",
        jd="Build Python API services and maintain reliable platform operations.",
    )

    merged = JobDeduplicator().deduplicate(
        [first, near],
        DeduplicationPolicy(near_duplicate_threshold=0.6),
    )
    separate = JobDeduplicator().deduplicate(
        [first, near],
        DeduplicationPolicy(near_duplicate_threshold=0.95),
    )

    assert len(merged.jobs) == 1
    assert len(separate.jobs) == 2


def test_conflicting_salary_is_preserved_as_merge_warning() -> None:
    first = job("mock-alpha", "alpha-001")
    second = job("mock-beta", "beta-991", salary="DKK 650000-760000 year")

    result = JobDeduplicator().deduplicate([first, second], DeduplicationPolicy())

    assert result.jobs[0].salary is not None
    assert "SALARY_CONFLICT" in result.jobs[0].warnings


def test_deduplication_is_input_order_invariant_and_idempotent() -> None:
    first = job("mock-alpha", "alpha-001", collected_offset=1)
    second = job("mock-beta", "beta-991", collected_offset=0)
    deduplicator = JobDeduplicator()

    forward = deduplicator.deduplicate([first, second], DeduplicationPolicy())
    reverse = deduplicator.deduplicate([second, first], DeduplicationPolicy())
    repeated = deduplicator.deduplicate(forward.jobs, DeduplicationPolicy())

    assert forward.model_dump(mode="json") == reverse.model_dump(mode="json")
    assert repeated.jobs == forward.jobs
