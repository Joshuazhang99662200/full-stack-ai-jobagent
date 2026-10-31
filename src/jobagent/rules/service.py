"""Single-variable proposals and content-addressed confirmed snapshots."""

import hashlib
import json
from datetime import datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.rules.registry import validate_change, validate_values
from jobagent.schemas.common import ContractModel
from jobagent.schemas.dynamic_rules import (
    DynamicRuleSet,
    RuleChangeNotice,
    RuleChangeRequest,
    RuleConfirmation,
    RuleProposal,
)


def digest(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )


def validate_snapshot(snapshot: DynamicRuleSet) -> DynamicRuleSet:
    snapshot = DynamicRuleSet.model_validate(snapshot.model_dump(mode="json"))
    validate_values(snapshot.values)
    if set(snapshot.values) != set(snapshot.provenance):
        raise ContractValidationError("Every dynamic variable requires exact provenance.")
    if any(
        source.source_kind != "user" or source.decided_at > snapshot.effective_at
        for source in snapshot.provenance.values()
    ):
        raise ContractValidationError("Rule provenance is unconfirmed or from the future.")
    if snapshot.version != digest(snapshot.model_dump(mode="json", exclude={"version"})):
        raise ContractValidationError("Dynamic rules snapshot digest mismatch.")
    return snapshot


def _validate_model(model: ContractModel) -> None:
    try:
        type(model).model_validate(model.model_dump(mode="json"))
    except ValidationError as error:
        raise ContractValidationError("Malformed dynamic-rule contract.") from error


def make_proposal(
    request: RuleChangeRequest,
    current: DynamicRuleSet | None,
    *,
    now: datetime,
) -> RuleProposal:
    _validate_model(request)
    validate_change(request)
    if now.tzinfo is None:
        raise ContractValidationError("Rule proposal time requires a timezone.")
    if current is not None:
        validate_snapshot(current)
        if current.candidate_id != request.candidate_id:
            raise ContractValidationError("Dynamic rule candidate scope mismatch.")
        if now < current.effective_at:
            raise ContractValidationError("Rule proposal time precedes the current version.")
        old_source = current.provenance.get(request.name)
        if old_source and request.provenance.decided_at <= old_source.decided_at:
            raise ContractValidationError("A newer owner decision is required for this variable.")
    if request.expected_version != (current.version if current else None):
        raise ContractValidationError("Dynamic rule proposal has a stale base version.")
    if now.tzinfo is None or request.provenance.decided_at > now:
        raise ContractValidationError("Rule decision time must precede the proposal.")
    old_value = current.values.get(request.name) if current else None
    if (
        current
        and request.name in current.values
        and old_value == request.value
        and current.provenance[request.name] == request.provenance
    ):
        raise ContractValidationError("Dynamic variable and provenance are unchanged.")
    old_text = json.dumps(old_value, ensure_ascii=False)
    new_text = json.dumps(request.value, ensure_ascii=False)
    scope_text = ""
    if request.owner_request is not None:
        scope_text = (
            f"Scope: round {request.owner_request.run_id} only; reusable settings unchanged. "
            if request.owner_request.scope == "round"
            else "Scope: reusable configuration. "
        )
    question = (
        f"Confirm one parameter change for {request.candidate_id}: {request.name}: "
        f"{old_text} -> {new_text}. "
        f"Base: {request.expected_version or 'initial'}. Source: "
        f"{request.provenance.source_ref}. {scope_text}"
        "This grants no send or delivery permission."
    )
    question_digest = digest({"question": question, "request": request.model_dump(mode="json")})
    identity = digest({"question_digest": question_digest, "proposed_at": now.isoformat()})
    return RuleProposal(
        proposal_id="RPROP_" + identity.removeprefix("sha256:")[:24].upper(),
        candidate_id=request.candidate_id,
        base_version=request.expected_version,
        request=request,
        old_value=old_value,
        question=question,
        question_digest=question_digest,
        proposed_at=now,
    )


def activate_proposal(
    proposal: RuleProposal,
    confirmation: RuleConfirmation,
    current: DynamicRuleSet | None,
) -> DynamicRuleSet:
    _validate_model(proposal)
    _validate_model(confirmation)
    expected = make_proposal(proposal.request, current, now=proposal.proposed_at)
    if expected != proposal:
        raise ContractValidationError("Original dynamic-rule question changed.")
    if confirmation.actor_id != proposal.request.provenance.decided_by:
        raise ContractValidationError("Rule confirmation actor does not match the declared owner.")
    if (
        confirmation.proposal_id != proposal.proposal_id
        or confirmation.question_digest != proposal.question_digest
        or confirmation.confirmed_at < proposal.proposed_at
        or not confirmation.answer.strip()
        or not confirmation.actor_id.strip()
    ):
        raise ContractValidationError(
            "Rule confirmation does not match the original question/time."
        )
    values = dict(current.values) if current else {}
    sources = dict(current.provenance) if current else {}
    values[proposal.request.name] = proposal.request.value
    sources[proposal.request.name] = proposal.request.provenance
    validate_values(values)
    snapshot = DynamicRuleSet(
        candidate_id=proposal.candidate_id,
        version="sha256:pending",
        parent_version=current.version if current else None,
        effective_at=confirmation.confirmed_at,
        values=values,
        provenance=sources,
    )
    snapshot.version = digest(snapshot.model_dump(mode="json", exclude={"version"}))
    return validate_snapshot(snapshot)


def change_notice(proposal: RuleProposal, snapshot: DynamicRuleSet) -> RuleChangeNotice:
    return RuleChangeNotice(
        candidate_id=snapshot.candidate_id,
        version=snapshot.version,
        name=proposal.request.name,
        old_value=proposal.old_value,
        new_value=proposal.request.value,
        effective_at=snapshot.effective_at,
        text=f"Variable {proposal.request.name}: "
        f"{json.dumps(proposal.old_value, ensure_ascii=False)} -> "
        f"{json.dumps(proposal.request.value, ensure_ascii=False)}; "
        f"effective from this version at {snapshot.effective_at.isoformat()}.",
    )
