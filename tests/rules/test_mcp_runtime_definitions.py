import pytest

from jobagent.errors import ContractValidationError
from jobagent.rules.registry import definitions, validate_change
from jobagent.rules.service import digest, validate_snapshot
from tests.rules.test_dynamic_registry import request
from tests.rules.test_evaluation import profile


def test_mcp_variables_name_real_runtime_consumers_without_personal_defaults():
    registry = {item.name: item for item in definitions()}
    for name in (
        "MCP_TOTAL",
        "MCP_BATCHSIZE",
        "MCP_MAX_PARALLEL",
        "LIEPIN_CALLS_PER_ROUND",
        "LIEPIN_DELIVERY_SPACING_SEC",
    ):
        definition = registry[name]
        assert definition.binding == "runtime"
        assert "mcp" in definition.consumer and definition.default is None


@pytest.mark.parametrize("value", [1, 4.999])
def test_new_spacing_proposal_cannot_weaken_minimum_invariant(value):
    with pytest.raises(ContractValidationError, match=r"five|spacing|minimum"):
        validate_change(request("LIEPIN_DELIVERY_SPACING_SEC", value))


def test_old_immutable_spacing_snapshot_stays_readable_but_is_not_reactivated():
    # Historical governance remains readable. The actual gateway rejects an
    # incompatible frozen value rather than changing old approvals/history.
    old = profile({"LIEPIN_DELIVERY_SPACING_SEC": 5})
    old.values["LIEPIN_DELIVERY_SPACING_SEC"] = 1
    old.version = digest(old.model_dump(mode="json", exclude={"version"}))
    assert validate_snapshot(old).version == old.version
