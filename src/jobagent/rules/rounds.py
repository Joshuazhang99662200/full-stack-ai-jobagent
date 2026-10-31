"""Exact round-only confirmations produce an ephemeral snapshot, never a new head."""

from datetime import datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.rules.service import activate_proposal, digest, validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.sourcing import ConfirmedRoundOverride


def apply_round_overrides(
    base: DynamicRuleSet,
    overrides: list[ConfirmedRoundOverride],
    *,
    run_id: str,
    now: datetime,
) -> DynamicRuleSet:
    base = validate_snapshot(base)
    if now.tzinfo is None or base.effective_at > now:
        raise ContractValidationError("Round override clock must follow the confirmed base.")
    if not overrides:
        return base
    values = dict(base.values)
    provenance = dict(base.provenance)
    effective_at = base.effective_at
    names: set[str] = set()
    for original in overrides:
        try:
            override = ConfirmedRoundOverride.model_validate(original.model_dump(mode="json"))
        except ValidationError as error:
            raise ContractValidationError("Invalid round-only confirmation contract.") from error
        proposal, confirmation = override.proposal, override.confirmation
        owner = proposal.request.owner_request
        if (
            owner is None or owner.scope != "round" or owner.run_id != run_id
            or owner.candidate_id != base.candidate_id or proposal.candidate_id != base.candidate_id
            or proposal.request.name not in owner.names
            or confirmation.actor_id != owner.actor_id
            or not owner.requested_at <= proposal.proposed_at <= confirmation.confirmed_at <= now
        ):
            raise ContractValidationError("Round override has mismatched owner, scope or time.")
        name = proposal.request.name
        if name in names:
            raise ContractValidationError("A round cannot override one variable twice.")
        names.add(name)
        # Each exact question was asked against the reusable base, independently.
        confirmed = activate_proposal(proposal, confirmation, base)
        values[name] = confirmed.values[name]
        provenance[name] = confirmed.provenance[name]
        effective_at = max(effective_at, confirmation.confirmed_at)
    result = DynamicRuleSet(
        candidate_id=base.candidate_id, version="sha256:pending", parent_version=base.version,
        effective_at=effective_at, values=values, provenance=provenance,
    )
    result.version = digest(result.model_dump(mode="json", exclude={"version"}))
    return validate_snapshot(result)
