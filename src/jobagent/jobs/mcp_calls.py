"""Pure configuration binding; no platform invocation or permission is produced."""

from datetime import datetime

from jobagent.errors import ContractValidationError
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.mcp_calls import McpRound, McpRoundRequest


def bind_mcp_round(
    request: McpRoundRequest,
    rules: DynamicRuleSet,
    *,
    now: datetime,
    code_revision: str,
) -> McpRound:
    validate_snapshot(rules)
    if now.tzinfo is None or rules.effective_at > now:
        raise ContractValidationError("MCP configuration requires current, aware decision time.")
    if request.candidate_id != rules.candidate_id or request.rules_version != rules.version:
        raise ContractValidationError("MCP candidate/rules version is stale or mismatched.")
    if request.code_revision not in {None, code_revision}:
        raise ContractValidationError("MCP plan uses a different code/runtime revision.")
    names = ["MCP_TOTAL", "MCP_MAX_PARALLEL", "MCP_BATCHSIZE"]
    if request.source == "liepin":
        names.append("LIEPIN_CALLS_PER_ROUND")
    missing = [name for name in names if name not in rules.values]
    if missing:
        raise ContractValidationError(
            "MCP parameters are missing: " + ", ".join(missing),
            details={"status": "not_integrated", "missing": missing},
        )
    values = {name: rules.values[name] for name in names}
    if any(type(value) is not int or value < 1 for value in values.values()):
        raise ContractValidationError("MCP quantities must be confirmed positive integers.")
    total = int(str(values["MCP_TOTAL"]))
    parallel = int(str(values["MCP_MAX_PARALLEL"]))
    size = int(str(values["MCP_BATCHSIZE"]))
    if parallel > total or size > total:
        raise ContractValidationError("MCP parallel/batch size conflicts with confirmed total.")
    spacing = rules.values.get("LIEPIN_DELIVERY_SPACING_SEC")
    if spacing is not None and (type(spacing) not in {int, float} or float(str(spacing)) < 5):
        raise ContractValidationError("Liepin delivery spacing must be at least five seconds.")
    return McpRound(
        **request.model_dump(exclude={"schema_version", "code_revision"}),
        code_revision=code_revision,
        opened_at=now,
        mcp_total=total,
        max_parallel=parallel,
        batch_size=size,
        liepin_call_limit=int(str(values["LIEPIN_CALLS_PER_ROUND"]))
        if request.source == "liepin"
        else None,
        delivery_spacing_seconds=float(str(spacing)) if spacing is not None else None,
    )
