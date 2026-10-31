import json
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_mcp_repository import NOW, call, provider, setup_round


def test_another_mcp_id_cannot_reset_the_same_sourcing_round(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpRoundRequest

    _, _, repo, run = setup_round(tmp_path, monkeypatch)
    alias = McpRoundRequest.model_validate(
        run.model_dump(include=set(McpRoundRequest.model_fields)) | {"run_id": "MCP_ALIAS"},
    )
    with pytest.raises(ContractValidationError, match=r"sourcing|bound|binding"):
        repo.start_round(alias, now=NOW)
    assert repo.status(run.run_id).actual_calls == 0


def test_recovery_can_resolve_a_dispatched_call_without_any_saved_response(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpCallReconciliation

    db, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    # Simulate process death after dispatch: finish() was never called.
    monkeypatch.setattr(
        "jobagent.storage.mcp_repository.runtime_fingerprint", lambda: "sha256:new-code-after-crash"
    )
    later = NOW + timedelta(days=1)
    resolved = repo.reconcile(
        McpCallReconciliation(
            call_id="ONE",
            result=provider(),
            source_reference="synthetic recovered positive readback",
            observed_by="synthetic owner",
            observed_at=later,
            positive_readback=True,
        ),
        now=later,
    )
    assert resolved.status == "success" and resolved.budget.actual_calls == 1
    with db.connect() as connection:
        original = json.loads(
            connection.execute(
                "SELECT receipt_json FROM mcp_results WHERE call_id='ONE'",
            ).fetchone()[0]
        )
    assert original["status"] == "unknown"
    assert repo.close_round("MCP_ONE", now=later).closed


def test_recovery_closes_an_admitted_but_never_dispatched_call_without_charging(
    tmp_path, monkeypatch
):
    from jobagent.schemas.mcp_calls import McpCallReconciliation

    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    result = repo.reconcile(
        McpCallReconciliation(
            call_id="ONE",
            result=provider("failed"),
            source_reference="synthetic stopped process before dispatch",
            observed_by="synthetic owner",
            observed_at=NOW,
            positive_readback=True,
        ),
        now=NOW,
    )
    assert result.status == "not_called" and not result.dispatched
    assert result.budget.actual_calls == 0 and not result.budget.activated
    assert not result.budget.halted
    assert repo.close_round("MCP_ONE", now=NOW).closed


def test_safe_internal_refusal_preserves_actionable_details_without_upstream_text(
    tmp_path, monkeypatch
):
    from jobagent.connectors.mcp_gateway import McpReadGateway

    _, _, repo, _ = setup_round(tmp_path, monkeypatch)

    def runner(request, checkpoint):
        raise ContractValidationError(
            "Shared detail budget exhausted.",
            details={"reason": "round_detail_limit", "remaining": 0},
        )

    receipt = McpReadGateway(repo, runner, clock=lambda: NOW).execute(call())
    assert receipt.status == "not_called"
    assert receipt.result.failure_details == {"reason": "round_detail_limit", "remaining": 0}
