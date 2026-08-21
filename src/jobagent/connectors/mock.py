"""Synthetic, fixture-backed read-only job discovery."""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from jobagent.errors import ContractValidationError, JobNotFoundError
from jobagent.schemas.job_intelligence import JobSearchQuery, SourceJobRecord
from jobagent.schemas.jobs import RecruiterInfo

_RECORDS = TypeAdapter(list[SourceJobRecord])


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


class MockJobSource:
    """Search synthetic source observations without exposing delivery operations."""

    def __init__(self, records: list[SourceJobRecord]) -> None:
        self._records = tuple(
            sorted(
                (record.model_copy(deep=True) for record in records),
                key=lambda item: item.source_job_id,
            )
        )
        self._by_source_id = {record.source_job_id: record for record in self._records}

    @classmethod
    def from_path(cls, path: Path) -> "MockJobSource":
        try:
            records = _RECORDS.validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise ContractValidationError(
                "Mock job fixture could not be loaded.",
                details={"fixture_name": path.name},
            ) from error
        return cls(records)

    def search(self, query: JobSearchQuery) -> list[SourceJobRecord]:
        tokens = _normalized(query.query).split()
        results: list[SourceJobRecord] = []
        for record in self._records:
            searchable = _normalized(
                " ".join(
                    (
                        record.source,
                        record.source_job_id,
                        record.title,
                        record.company,
                        record.location,
                        record.jd_raw,
                    )
                )
            )
            if not all(token in searchable for token in tokens):
                continue
            if not self._matches_optional_filters(record, query):
                continue
            results.append(record.model_copy(deep=True))
        return results

    def fetch_job(self, source_job_id: str) -> SourceJobRecord:
        record = self._by_source_id.get(source_job_id)
        if record is None:
            raise JobNotFoundError(
                "Source job was not found.",
                details={"source_job_id": source_job_id},
            )
        return record.model_copy(deep=True)

    def get_recruiter(self, source_job_id: str) -> RecruiterInfo | None:
        recruiter = self.fetch_job(source_job_id).recruiter
        return None if recruiter is None else recruiter.model_copy(deep=True)

    @staticmethod
    def _matches_optional_filters(record: SourceJobRecord, query: JobSearchQuery) -> bool:
        filters = (
            (record.title, query.title),
            (record.company, query.company),
            (record.location, query.location),
            (record.source_job_id, query.source_job_id),
        )
        return all(
            expected is None or _normalized(actual) == _normalized(expected)
            for actual, expected in filters
        )
