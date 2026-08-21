from datetime import UTC, datetime

import pytest

from jobagent.errors import JobNormalizationError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.job_intelligence import SourceJobRecord


def source_job(**updates: object) -> SourceJobRecord:
    values: dict[str, object] = {
        "source": " Mock Alpha ",
        "source_job_id": " alpha-001 ",
        "title": "Ｐｙｔｈｏｎ   Platform\nEngineer",  # noqa: RUF001 - NFKC fixture
        "company": " Example   Labs ",
        "location": " Copenhagen ",
        "salary_text": "DKK 600000-720000 year",
        "jd_raw": "Build Python APIs.\n\nMaintain platform reliability.",
        "url": "https://jobs.example.test/alpha-001",
        "published_at": datetime(2026, 8, 18, tzinfo=UTC),
        "collected_at": datetime(2026, 8, 21, tzinfo=UTC),
    }
    values.update(updates)
    return SourceJobRecord(**values)


def test_normalizer_canonicalizes_unicode_whitespace_and_salary() -> None:
    normalized = JobNormalizer().normalize(source_job())

    assert normalized.title == "Python Platform Engineer"
    assert normalized.company == "Example Labs"
    assert normalized.location == "Copenhagen"
    assert normalized.jd_raw == "Build Python APIs. Maintain platform reliability."
    assert normalized.salary is not None
    assert normalized.salary.currency == "DKK"
    assert normalized.salary.minimum == 600000
    assert normalized.salary.maximum == 720000
    assert normalized.salary.period == "year"


def test_normalized_id_is_stable_for_source_identity() -> None:
    normalizer = JobNormalizer()

    first = normalizer.normalize(source_job())
    second = normalizer.normalize(
        source_job(title="A changed display title", jd_raw="A changed description.")
    )

    assert first.id == second.id
    assert first.id.startswith("JOB_")


def test_normalizer_preserves_source_provenance() -> None:
    normalized = JobNormalizer().normalize(source_job())

    assert len(normalized.provenance) == 1
    assert normalized.provenance[0].source == "Mock Alpha"
    assert normalized.provenance[0].source_id == "alpha-001"
    assert str(normalized.provenance[0].url).endswith("/alpha-001")


def test_ambiguous_salary_is_warning_not_invention() -> None:
    normalized = JobNormalizer().normalize(source_job(salary_text="Competitive package"))

    assert normalized.salary is None
    assert normalized.warnings == ["SALARY_UNPARSED"]


def test_invalid_untrusted_source_record_returns_typed_error() -> None:
    invalid = source_job().model_copy(update={"title": ""})

    with pytest.raises(JobNormalizationError) as captured:
        JobNormalizer().normalize(invalid)

    assert captured.value.code == "NORMALIZATION_ERROR"
