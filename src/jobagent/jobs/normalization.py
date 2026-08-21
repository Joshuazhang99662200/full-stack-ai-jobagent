"""Deterministic source-record normalization."""

import hashlib
import re
import unicodedata
from decimal import Decimal

from pydantic import ValidationError

from jobagent.errors import JobNormalizationError
from jobagent.schemas.common import MoneyRange, ProvenanceRecord
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.jobs import NormalizedJob

_SALARY_PATTERN = re.compile(
    r"^(?P<currency>[A-Za-z]{3})\s+"
    r"(?P<minimum>\d+(?:\.\d+)?)-(?P<maximum>\d+(?:\.\d+)?)\s+"
    r"(?P<period>\S+)$"
)


def _canonical(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


class JobNormalizer:
    """Normalize observable fields without interpreting the JD."""

    def normalize(self, raw_record: SourceJobRecord) -> NormalizedJob:
        try:
            record = SourceJobRecord.model_validate(raw_record.model_dump(mode="python"))
        except (AttributeError, TypeError, ValidationError) as error:
            raise JobNormalizationError(
                "Source job record violated the normalization contract.",
                details={"operation": "normalize_job"},
            ) from error

        source = _canonical(record.source)
        source_job_id = _canonical(record.source_job_id)
        identity = f"{source.casefold()}\0{source_job_id.casefold()}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        salary, salary_warning = self._parse_salary(record.salary_text)
        warnings = [salary_warning] if salary_warning is not None else []
        return NormalizedJob(
            id=f"JOB_{digest[:16].upper()}",
            source=source,
            source_job_id=source_job_id,
            title=_canonical(record.title),
            company=_canonical(record.company),
            location=_canonical(record.location),
            salary=salary,
            jd_raw=_canonical(record.jd_raw),
            recruiter=record.recruiter,
            url=record.url,
            published_at=record.published_at,
            collected_at=record.collected_at,
            provenance=[
                ProvenanceRecord(
                    source=source,
                    source_id=source_job_id,
                    url=record.url,
                    collected_at=record.collected_at,
                )
            ],
            warnings=warnings,
        )

    @staticmethod
    def _parse_salary(salary_text: str | None) -> tuple[MoneyRange | None, str | None]:
        if salary_text is None or not salary_text.strip():
            return None, None
        match = _SALARY_PATTERN.fullmatch(_canonical(salary_text))
        if match is None:
            return None, "SALARY_UNPARSED"
        return (
            MoneyRange(
                currency=match.group("currency").upper(),
                minimum=Decimal(match.group("minimum")),
                maximum=Decimal(match.group("maximum")),
                period=match.group("period").casefold(),
            ),
            None,
        )
