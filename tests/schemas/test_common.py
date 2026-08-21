from datetime import date

import pytest
from pydantic import ValidationError

from jobagent.errors import MissingEvidenceError
from jobagent.schemas.common import SourceReference, SourceType, TimeRange


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourceReference(type=SourceType.RESUME, reference="page:1", surprise=True)


def test_time_range_rejects_reverse_dates() -> None:
    with pytest.raises(ValidationError):
        TimeRange(start=date(2025, 1, 1), end=date(2024, 1, 1))


def test_domain_error_has_stable_code() -> None:
    error = MissingEvidenceError("RAG implementation evidence is absent")
    assert error.code == "MISSING_EVIDENCE"
