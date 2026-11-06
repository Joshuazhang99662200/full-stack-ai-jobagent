"""A readable platform must never imply custom-artifact delivery support."""

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


@pytest.mark.parametrize("job_kind", ["1", "2", None, "9"])
def test_missing_custom_artifact_support_stops_before_any_platform_action(job_kind):
    result = LiepinCliDeliverySource().submit_application(package(job_kind=job_kind))
    assert result.status is SendResultStatus.USER_INTERVENTION_REQUIRED
    assert result.intervention_reason is InterventionReason.PLATFORM_CHANGED
    assert "approved tailored attachment and message" in (result.failure_reason or "")
    assert "No platform submission was attempted" in (result.failure_reason or "")
    assert result.external_reference is None


def test_foreign_platform_package_is_rejected():
    with pytest.raises(ContractValidationError, match="only handles Liepin"):
        LiepinCliDeliverySource().submit_application(package(source="zhaopin"))
