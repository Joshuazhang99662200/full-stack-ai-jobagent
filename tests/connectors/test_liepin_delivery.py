"""A readable platform must never imply custom-artifact delivery support."""

import subprocess
from collections.abc import Sequence

import pytest

from jobagent.applications.ports import ApplicationDeliverySource
from jobagent.connectors.liepin_delivery import LiepinCliDeliverySource
from jobagent.errors import ContractValidationError
from jobagent.schemas.applications import InterventionReason, SendResultStatus
from tests.applications.conftest import build_package


def package(*, source="liepin", job_kind="2"):
    result = build_package()
    result.job.source = source
    result.job.job_kind = job_kind
    return result


def test_source_satisfies_single_delivery_port():
    source = LiepinCliDeliverySource()
    assert isinstance(source, ApplicationDeliverySource)
    for forbidden in ("submit_applications", "submit_all", "submit_batch", "send_all"):
        assert not hasattr(source, forbidden)


@pytest.mark.parametrize("job_kind", ["1", "2"])
@pytest.mark.parametrize("platform_output", [b"{}", b'{"applyId":"A-1"}', b"ok"])
def test_missing_custom_artifact_support_stops_before_any_platform_action(
    job_kind, platform_output
):
    commands = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, platform_output, b"")

    result = LiepinCliDeliverySource(runner=runner).submit_application(package(job_kind=job_kind))
    assert result.status is SendResultStatus.USER_INTERVENTION_REQUIRED
    assert result.intervention_reason is InterventionReason.PLATFORM_CHANGED
    assert "approved tailored attachment and message" in (result.failure_reason or "")
    assert "No platform submission was attempted" in (result.failure_reason or "")
    assert result.external_reference is None
    assert commands == []


@pytest.mark.parametrize("job_kind", [None, "9"])
def test_missing_or_unrecognised_posting_kind_is_not_guessed(job_kind):
    with pytest.raises(ContractValidationError):
        LiepinCliDeliverySource().submit_application(package(job_kind=job_kind))


def test_foreign_platform_package_is_rejected():
    with pytest.raises(ContractValidationError, match="only handles Liepin"):
        LiepinCliDeliverySource().submit_application(package(source="zhaopin"))


def test_platform_credentials_or_missing_executable_are_not_touched():
    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("Must not probe login, online resume, or upstream submit")

    result = LiepinCliDeliverySource(executable="missing-cli", runner=runner).submit_application(
        package()
    )
    assert result.status is SendResultStatus.USER_INTERVENTION_REQUIRED
