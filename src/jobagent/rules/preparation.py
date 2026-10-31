"""Pure first-run questions; ordinary tasks never reopen owner configuration."""

from datetime import datetime

from jobagent.errors import ContractValidationError
from jobagent.rules.registry import definitions
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.configuration import (
    BASE_CONFIGURATION_NAMES,
    ConfigurationField,
    ConfigurationFieldStatus,
    ConfigurationPreparationRequest,
    ConfigurationPreparationResult,
    ConfigurationPreparationStatus,
)
from jobagent.schemas.dynamic_rules import DynamicRuleSet

_LABELS = {
    "QUERIES_PER_SITE_PER_ROUND": ("每站每轮查询组合数", "组/站/轮"),
    "TOP_PER_QUERY": ("每查询最多取数", "条/查询"),
    "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND": ("每站每轮详情尝试数", "次/站/轮"),
    "DETAIL_CAP_PER_DAY": ("每站每日详情额度", "次/站/日"),
}


def prepare_configuration(
    request: ConfigurationPreparationRequest,
    snapshot: DynamicRuleSet | None,
    *,
    initialized: bool,
    now: datetime | None = None,
    consumed_names: set[str] | None = None,
) -> ConfigurationPreparationResult:
    request = ConfigurationPreparationRequest.model_validate(request.model_dump(mode="json"))
    if snapshot is not None:
        snapshot = validate_snapshot(snapshot)
        if snapshot.candidate_id != request.candidate_id:
            raise ContractValidationError("Configuration candidate scope mismatch.")
    mode = "ordinary_run" if initialized and request.mode == "initial_setup" else request.mode
    owner = request.owner_request
    conflicts = list(request.conflicts)
    if mode == "owner_requested_change" and (
        owner is None or owner.candidate_id != request.candidate_id
    ):
        conflicts.append("explicit_matching_owner_request_required")
    if now is not None:
        if now.tzinfo is None:
            raise ContractValidationError("Configuration clock requires a timezone.")
        if (mode == "owner_requested_change" and owner is not None
                and owner.requested_at > now):
            conflicts.append("owner_request_is_in_the_future")
    if request.expected_version is not None and (
        snapshot is None or snapshot.version != request.expected_version
    ):
        conflicts.append("configuration_version_changed")
    values = snapshot.values if snapshot else {}
    provenance = snapshot.provenance if snapshot else {}
    requested_names = list(owner.names) if mode == "owner_requested_change" and owner else []
    consumed = set(consumed_names or ())
    if owner is not None and mode == "owner_requested_change":
        consumed.update(
            name for name in requested_names
            if name in provenance and owner.requested_at <= provenance[name].decided_at
        )
    requested = [name for name in requested_names if name not in consumed]
    if requested_names and not requested:
        conflicts.append("owner_request_already_consumed_or_stale")
    names = list(dict.fromkeys((
        *BASE_CONFIGURATION_NAMES, *request.required_names, *requested_names,
    )))
    known = {item.name: item for item in definitions()}
    fields = []
    for name in names:
        definition = known.get(name)
        supported = definition is not None and definition.binding in {"runtime", "proposal_only"}
        field_status: ConfigurationFieldStatus = (
            "unsupported" if not supported else "change_requested" if name in requested
            else "confirmed" if name in values else "missing"
        )
        label, unit = _LABELS.get(name, (name, "按变量契约"))
        fields.append(ConfigurationField(
            name=name, label=label, unit=unit, value=values.get(name), status=field_status,
            consumer=definition.consumer if definition else "Unknown consumer",
            provenance=provenance.get(name),
        ))
    missing = [field for field in fields if field.status == "missing"]
    unsupported = [field for field in fields if field.status == "unsupported"]
    questions = []
    if not conflicts and mode in {"initial_setup", "owner_requested_change"}:
        question_fields = missing if mode == "initial_setup" else [
            field for field in fields if field.name in requested and field.status != "unsupported"
        ]
        questions = [
            f"请裁定{field.label} ({field.name}, 单位: {field.unit})。"
            for field in question_fields
        ]
    complete_baseline = all(name in values for name in BASE_CONFIGURATION_NAMES)
    can_initialize = (
        complete_baseline and not initialized
        and not conflicts and not unsupported and not questions
    )
    status: ConfigurationPreparationStatus
    if conflicts:
        status = "blocked_by_conflict"
    elif unsupported:
        status = "unsupported_consumer"
        questions = []
    elif questions:
        status = "needs_user_decision"
    elif missing or (not initialized and mode == "ordinary_run"):
        status = "blocked_by_missing_configuration"
    elif can_initialize:
        status = "ready_to_initialize"
    else:
        status = "ready"
    return ConfigurationPreparationResult(
        candidate_id=request.candidate_id, task_id=request.task_id, task_type=request.task_type,
        mode=mode, initialized=initialized, ready=status == "ready", can_initialize=can_initialize,
        ask_user=bool(questions), status=status, questions=questions, fields=fields,
        rules_version=snapshot.version if snapshot else None, code_revision=request.code_revision,
        reasons=conflicts or [field.name for field in missing + unsupported],
    )
