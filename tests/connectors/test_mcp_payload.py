from datetime import UTC, datetime

import pytest

from jobagent.connectors.cli_source import CliListingSource
from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.sources import SourceRegistry

NOW = datetime(2026, 10, 31, 1, tzinfo=UTC)


def parser():
    def forbidden_runner(*_args):
        raise AssertionError("Parsing already-observed data must not execute a process.")

    return CliListingSource(SourceRegistry.default().get("liepin"), runner=forbidden_runner)


def test_parse_observed_payload_without_another_external_call():
    payload = {
        "code": 0,
        "data": {
            "jobs": [
                {
                    "jobId": "SYNTH_PAYLOAD",
                    "jobName": "Synthetic research role",
                    "company": "Synthetic laboratory",
                    "jobDetailUrl": "https://example.org/jobs/SYNTH",
                }
            ]
        },
    }
    result = parser().parse_listings(payload, collected_at=NOW)
    assert len(result) == 1 and result[0].source_job_id == "SYNTH_PAYLOAD"
    assert result[0].collected_at == NOW and result[0].source == "liepin"


def test_parse_explicit_successful_empty_list_without_inventing_results():
    assert parser().parse_listings({"code": 0, "data": {"jobs": []}}, collected_at=NOW) == []


@pytest.mark.parametrize("payload", [{"summary": "nothing found"}, {"jobs": [None]}])
def test_unrecognized_or_invalid_rows_cannot_become_successful_zero(payload):
    with pytest.raises(InvalidProviderOutputError):
        parser().parse_listings(payload, collected_at=NOW)


def test_business_gate_is_checked_before_empty_list():
    with pytest.raises(UserInterventionRequiredError):
        parser().parse_listings({"code": 429001, "jobs": []}, collected_at=NOW)
