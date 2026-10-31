from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.sourcing import SourcingRunRequest
from jobagent.storage.sourcing_repository import SqliteSourcingRepository
from tests.jobs.test_query_selection import listing
from tests.storage.test_configured_sourcing import NOW, configured

CODE = "sha256:synthetic-mcp-runtime"


def setup_round(tmp_path, monkeypatch, **changes):
    from jobagent.schemas.mcp_calls import McpRoundRequest
    from jobagent.storage.mcp_repository import SqliteMcpRepository

    monkeypatch.setattr("jobagent.storage.sourcing_repository.runtime_fingerprint", lambda: CODE)
    monkeypatch.setattr("jobagent.storage.mcp_repository.runtime_fingerprint", lambda: CODE)
    values = dict(
        MCP_TOTAL=6,
        MCP_MAX_PARALLEL=2,
        MCP_BATCHSIZE=3,
        LIEPIN_CALLS_PER_ROUND=8,
        LIEPIN_DELIVERY_SPACING_SEC=5,
    )
    values.update(changes)
    db, rules = configured(tmp_path, **values)
    SqliteSourcingRepository(db).start_run(
        SourcingRunRequest(
            run_id="SOURCE_ONE",
            source="liepin",
            candidate_id=rules.candidate_id,
            rules_version=rules.version,
        ),
        now=NOW,
        daily_cap=9,
    )
    repo = SqliteMcpRepository(db)
    run = repo.start_round(
        McpRoundRequest(
            run_id="MCP_ONE",
            sourcing_run_id="SOURCE_ONE",
            source="liepin",
            candidate_id=rules.candidate_id,
            rules_version=rules.version,
        ),
        now=NOW,
    )
    return db, rules, repo, run


def call(number="ONE", *, operation="view", batch="BATCH_ONE", run="MCP_ONE"):
    from jobagent.schemas.mcp_calls import McpCallRequest

    return McpCallRequest(
        call_id=number,
        run_id=run,
        batch_id=batch,
        operation=operation,
        arguments={"id": number} if operation == "view" else {"query": number},
        search_term=number if operation == "search" else None,
        source_job_id=number if operation == "view" else None,
        target_url=f"https://www.liepin.com/job/{number}.shtml" if operation == "view" else None,
    )


def next_sourcing_round(repo, rules):
    SqliteSourcingRepository(repo.database).start_run(
        SourcingRunRequest(
            run_id="SOURCE_TWO",
            source="liepin",
            candidate_id=rules.candidate_id,
            rules_version=rules.version,
        ),
        now=NOW,
        daily_cap=9,
    )


def provider(status="success", **changes):
    from jobagent.schemas.mcp_calls import McpProviderResult

    return McpProviderResult(status=status, payload={"synthetic": True}, **changes)


def test_planning_and_admission_do_not_bill_without_actual_dispatch(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    budget = repo.status("MCP_ONE")
    assert budget.actual_calls == 0 and not budget.activated
    assert budget.previous_delivery_debit == 0 and budget.search_view_calls == 0
    repo.finish("ONE", provider("failed"), now=NOW)
    assert repo.status("MCP_ONE").actual_calls == 0


def test_pre_dispatch_rate_error_does_not_activate_mcp_business_usage(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    receipt = repo.finish("ONE", provider("gate", error_code="429001"), now=NOW)
    assert receipt.status == "not_called" and not receipt.dispatched
    assert not receipt.budget.activated and not receipt.budget.halted


def test_dispatch_is_the_atomic_shared_detail_attempt(tmp_path, monkeypatch):
    db, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    receipt = repo.finish("ONE", provider("failed"), now=NOW)
    assert receipt.dispatched and receipt.budget.actual_calls == 1
    budget = SqliteSourcingRepository(db).budget("liepin", daily_cap=9, now=NOW)
    assert budget.read_today == 1
    with pytest.raises(ContractValidationError, match=r"dispatch|already"):
        repo.mark_dispatched("ONE", now=NOW)


def test_unfinished_batch_and_parallel_slots_are_enforced_atomically(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch, DETAIL_ATTEMPTS_PER_SITE_PER_ROUND=5)
    repo.open_batch([call("ONE"), call("TWO"), call("THREE")], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.mark_dispatched("TWO", now=NOW)
    with pytest.raises(ContractValidationError, match=r"parallel"):
        repo.mark_dispatched("THREE", now=NOW)
    with pytest.raises(ContractValidationError, match=r"batch"):
        repo.open_batch([call("FOUR", batch="BATCH_TWO")], now=NOW)
    repo.finish("ONE", provider(), now=NOW)
    repo.mark_dispatched("THREE", now=NOW)


def test_gate_halts_the_source_across_rounds_and_read_entry_points(tmp_path, monkeypatch):
    db, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call("ONE"), call("TWO")], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider("gate", error_code="429001"), now=NOW)
    with pytest.raises(ContractValidationError, match=r"halt"):
        repo.mark_dispatched("TWO", now=NOW)
    assert SqliteSourcingRepository(db).budget("liepin", daily_cap=9, now=NOW).halted
    assert repo.status("MCP_ONE").actual_calls == 1


def test_exact_complete_replay_is_readonly_but_unknown_cannot_retry(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    request = call()
    repo.open_batch([request], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    receipt = repo.finish("ONE", provider(), now=NOW)
    _, replay = repo.open_batch([request], now=NOW)
    assert replay == [receipt]
    with pytest.raises(ContractValidationError, match=r"different|changed"):
        repo.open_batch([request.model_copy(update={"arguments": {"id": "CHANGED"}})], now=NOW)


def test_unknown_dispatch_outcome_blocks_close_and_next_batch(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider("unknown"), now=NOW)
    with pytest.raises(ContractValidationError, match=r"unknown|unresolved"):
        repo.close_round("MCP_ONE", now=NOW)
    with pytest.raises(ContractValidationError, match=r"unknown|unresolved|batch|halt"):
        repo.open_batch([call("TWO", batch="BATCH_TWO")], now=NOW)


def test_search_and_view_share_call_limit_and_search_top_is_consumed(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch, LIEPIN_CALLS_PER_ROUND=2)
    request = call(operation="search")
    repo.open_batch([request], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    rows = [listing(n, source="liepin") for n in range(5)]
    result = repo.finish("ONE", provider(listings=rows, loaded=True), now=NOW)
    assert result.selection.requested == 3 and result.selection.taken_count == 3
    repo.open_batch([call("TWO", batch="BATCH_TWO")], now=NOW)
    repo.mark_dispatched("TWO", now=NOW)
    repo.finish("TWO", provider(), now=NOW)
    repo.open_batch([call("THREE", batch="BATCH_THREE")], now=NOW)
    with pytest.raises(ContractValidationError, match=r"allowance|limit"):
        repo.mark_dispatched("THREE", now=NOW)
    assert repo.status("MCP_ONE").search_view_calls == 2


def test_missing_unconfirmed_batchsize_never_activates_guess(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpRoundRequest
    from jobagent.storage.mcp_repository import SqliteMcpRepository

    db, rules = configured(tmp_path, MCP_TOTAL=6, MCP_MAX_PARALLEL=2, LIEPIN_CALLS_PER_ROUND=8)
    with pytest.raises(ContractValidationError, match=r"MCP_BATCHSIZE"):
        SqliteMcpRepository(db).start_round(
            McpRoundRequest(
                run_id="MCP_ONE",
                sourcing_run_id="SOURCE_ONE",
                source="liepin",
                candidate_id=rules.candidate_id,
                rules_version=rules.version,
            ),
            now=NOW,
        )


def test_stale_code_and_expired_round_cannot_dispatch(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    monkeypatch.setattr(
        "jobagent.storage.mcp_repository.runtime_fingerprint", lambda: "sha256:changed-runtime"
    )
    with pytest.raises(ContractValidationError, match=r"revision|runtime|code"):
        repo.mark_dispatched("ONE", now=NOW)
    monkeypatch.setattr("jobagent.storage.mcp_repository.runtime_fingerprint", lambda: CODE)
    with pytest.raises(ContractValidationError, match=r"expired|day"):
        repo.mark_dispatched("ONE", now=NOW + timedelta(days=1))


def test_unknown_call_reconciliation_records_actual_readback_without_retry(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpCallReconciliation

    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    original = repo.finish("ONE", provider("unknown"), now=NOW)
    resolution = McpCallReconciliation(
        call_id="ONE",
        result=provider(),
        source_reference="synthetic positive tool readback",
        observed_by="synthetic owner",
        observed_at=NOW,
        positive_readback=True,
    )
    resolved = repo.reconcile(resolution, now=NOW)
    assert resolved.status == "success" and original.status == "unknown"
    assert repo.reconcile(resolution, now=NOW) == resolved
    assert repo.status("MCP_ONE").actual_calls == 1
    assert repo.status("MCP_ONE").halted
    assert repo.close_round("MCP_ONE", now=NOW).closed
    assert repo.open_batch([call()], now=NOW)[1] == [resolved]


def delivery_intent(number="ONE", *, run="MCP_ONE"):
    from jobagent.schemas.mcp_calls import McpDeliveryIntent

    return McpDeliveryIntent(
        action_id="DELIVERY_" + number,
        run_id=run,
        source_job_id="JOB_" + number,
        item_approval_reference="synthetic item approval " + number,
    )


def delivery_observation(number="ONE", *, at=NOW, status="sent", **changes):
    from jobagent.schemas.mcp_calls import McpDeliveryObservation

    return McpDeliveryObservation.model_validate(
        dict(
            action_id="DELIVERY_" + number,
            run_id="MCP_ONE",
            source_job_id="JOB_" + number,
            status=status,
            occurred_at=at,
            observed_at=at,
            observed_by="synthetic owner",
            source_reference="synthetic actual capture " + number,
            external_reference="synthetic external operation " + number,
            readback_reference="synthetic positive readback " + number,
            evidence_text="Synthetic actual platform delivery observation.",
            positive_readback=status == "sent",
        )
        | changes
    )


def test_host_delivery_is_serial_spaced_and_never_grants_execution_permission(
    tmp_path, monkeypatch
):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider(), now=NOW)
    handoff = repo.prepare_delivery(delivery_intent(), now=NOW)
    assert not handoff.executable and not handoff.grants_delivery_permission
    with pytest.raises(ContractValidationError, match="readback"):
        repo.prepare_delivery(delivery_intent("TWO"), now=NOW + timedelta(seconds=10))
    repo.record_delivery(delivery_observation(), now=NOW)
    with pytest.raises(ContractValidationError, match="spacing"):
        repo.prepare_delivery(delivery_intent("TWO"), now=NOW + timedelta(seconds=4))
    repo.prepare_delivery(delivery_intent("TWO"), now=NOW + timedelta(seconds=5))
    assert repo.status("MCP_ONE").actual_calls == 1


def test_closed_previous_round_delivery_facts_are_debited_only_at_next_dispatch(
    tmp_path, monkeypatch
):
    from jobagent.schemas.mcp_calls import McpRoundRequest

    _, rules, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider(), now=NOW)
    repo.prepare_delivery(delivery_intent(), now=NOW)
    repo.record_delivery(delivery_observation(), now=NOW)
    repo.close_round("MCP_ONE", now=NOW)
    next_sourcing_round(repo, rules)
    repo.start_round(
        McpRoundRequest(
            run_id="MCP_TWO",
            sourcing_run_id="SOURCE_TWO",
            source="liepin",
            candidate_id=rules.candidate_id,
            rules_version=rules.version,
        ),
        now=NOW,
    )
    assert not repo.status("MCP_TWO").activated
    assert repo.status("MCP_TWO").previous_delivery_debit == 0
    repo.open_batch([call("TWO", run="MCP_TWO", batch="BATCH_TWO")], now=NOW)
    repo.mark_dispatched("TWO", now=NOW)
    budget = repo.status("MCP_TWO")
    assert budget.previous_run_id == "MCP_ONE" and budget.previous_delivery_debit == 1
    assert budget.base_allowance == 8 and budget.starting_remaining == 7
    assert budget.actual_calls == 1 and budget.search_view_calls == 1
    with pytest.raises(ContractValidationError, match=r"different|frozen|closed"):
        repo.record_delivery(delivery_observation(at=NOW + timedelta(seconds=1)), now=NOW)


def test_previous_actual_round_cannot_be_omitted_before_it_is_resolved(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpRoundRequest

    _, rules, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider(), now=NOW)
    next_sourcing_round(repo, rules)
    repo.start_round(
        McpRoundRequest(
            run_id="MCP_TWO",
            sourcing_run_id="SOURCE_TWO",
            source="liepin",
            candidate_id=rules.candidate_id,
            rules_version=rules.version,
        ),
        now=NOW,
    )
    repo.open_batch([call("TWO", run="MCP_TWO", batch="BATCH_TWO")], now=NOW)
    with pytest.raises(ContractValidationError, match=r"closed|resolved"):
        repo.mark_dispatched("TWO", now=NOW)
    assert repo.status("MCP_TWO").actual_calls == 0


def test_unknown_host_delivery_needs_explicit_reconciliation_before_close(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider(), now=NOW)
    repo.prepare_delivery(delivery_intent(), now=NOW)
    original = delivery_observation(status="unknown")
    repo.record_delivery(original, now=NOW)
    with pytest.raises(ContractValidationError, match=r"unknown|unresolved"):
        repo.close_round("MCP_ONE", now=NOW)
    resolved = repo.reconcile_delivery(delivery_observation(), now=NOW)
    assert resolved.status == "sent" and original.status == "unknown"
    assert repo.status("MCP_ONE").actual_calls == 1
    assert repo.close_round("MCP_ONE", now=NOW).closed


def test_one_external_delivery_cannot_be_counted_twice(tmp_path, monkeypatch):
    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call()], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    repo.finish("ONE", provider(), now=NOW)
    repo.prepare_delivery(delivery_intent(), now=NOW)
    repo.record_delivery(delivery_observation(), now=NOW)
    at = NOW + timedelta(seconds=5)
    repo.prepare_delivery(delivery_intent("TWO"), now=at)
    with pytest.raises(ContractValidationError, match=r"external|already|duplicate"):
        repo.record_delivery(
            delivery_observation(
                "TWO",
                at=at,
                external_reference="synthetic external operation ONE",
            ),
            now=at,
        )


def test_mcp_scope_and_observation_references_cannot_be_blank_or_case_aliased():
    from jobagent.schemas.mcp_calls import McpRoundRequest

    with pytest.raises(ValueError, match=r"canonical|source"):
        McpRoundRequest(
            run_id="MCP_SYNTH",
            sourcing_run_id="SRC_SYNTH",
            source="Liepin",
            candidate_id="CAND_SYNTHETIC",
            rules_version="sha256:synthetic",
        )
    with pytest.raises(ValueError, match=r"blank|empty"):
        delivery_observation(source_reference=" ")


def test_inflight_mcp_search_cannot_be_executed_again_through_normal_listing_route(
    tmp_path,
    monkeypatch,
):
    from jobagent.storage.query_repository import SqliteQueryRepository

    db, _, repo, _ = setup_round(tmp_path, monkeypatch)
    repo.open_batch([call(operation="search")], now=NOW)
    repo.mark_dispatched("ONE", now=NOW)
    with pytest.raises(ContractValidationError, match=r"different|claimed|unknown"):
        SqliteQueryRepository(db).claim(
            "MCP_ONE",
            run_id="SOURCE_ONE",
            source="liepin",
            query="ONE",
            request_digest="sha256:different-normal-cli-request",
            now=NOW,
        )
    assert repo.status("MCP_ONE").actual_calls == 1
