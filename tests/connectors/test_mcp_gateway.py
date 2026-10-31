from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from jobagent.errors import ContractValidationError
from tests.jobs.test_query_selection import listing
from tests.storage.test_configured_sourcing import NOW
from tests.storage.test_mcp_repository import call, provider, setup_round


def test_startup_failure_is_not_billed_and_completed_replay_calls_nothing(tmp_path, monkeypatch):
    from jobagent.connectors.mcp_gateway import McpReadGateway

    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    count = 0

    def runner(request, dispatched):
        nonlocal count
        count += 1
        raise OSError("Synthetic startup failure")

    gateway = McpReadGateway(repo, runner, clock=lambda: NOW)
    first = gateway.execute(call())
    second = gateway.execute(call())
    assert first == second and first.status == "not_called"
    assert not first.dispatched and repo.status("MCP_ONE").actual_calls == 0 and count == 1


def test_post_dispatch_failure_is_unknown_and_never_retried(tmp_path, monkeypatch):
    from jobagent.connectors.mcp_gateway import McpReadGateway

    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    count = 0

    def runner(request, dispatched):
        nonlocal count
        count += 1
        dispatched()
        raise TimeoutError("Synthetic unknown external outcome")

    gateway = McpReadGateway(repo, runner, clock=lambda: NOW)
    first = gateway.execute(call())
    assert first.status == "unknown" and first.dispatched
    with pytest.raises(ContractValidationError, match=r"unknown|unresolved"):
        gateway.execute(call())
    assert count == 1 and repo.status("MCP_ONE").actual_calls == 1


def test_actual_search_uses_the_query_consumer_and_replay_is_saved(tmp_path, monkeypatch):
    from jobagent.connectors.mcp_gateway import McpReadGateway

    _, _, repo, _ = setup_round(tmp_path, monkeypatch)
    count = 0

    def runner(request, dispatched):
        nonlocal count
        count += 1
        dispatched()
        return provider(listings=[listing(n, source="liepin") for n in range(5)], loaded=True)

    gateway = McpReadGateway(repo, runner, clock=lambda: NOW)
    receipt = gateway.execute(call(operation="search"))
    assert receipt.status == "success" and receipt.selection.taken_count == 3
    assert len(receipt.result.listings) == 3 and receipt.result.payload is None
    assert gateway.execute(call(operation="search")) == receipt and count == 1


def test_parallel_calls_are_bounded_and_next_batch_cannot_overtake(tmp_path, monkeypatch):
    from jobagent.connectors.mcp_gateway import McpReadGateway

    _, _, repo, _ = setup_round(tmp_path, monkeypatch, DETAIL_ATTEMPTS_PER_SITE_PER_ROUND=5)
    entered, release = Event(), Event()
    lock = Lock()
    active = peak = 0

    def runner(request, dispatched):
        nonlocal active, peak
        dispatched()
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
        assert release.wait(10)
        with lock:
            active -= 1
        return provider()

    gateway = McpReadGateway(repo, runner, clock=lambda: NOW)
    with ThreadPoolExecutor(max_workers=1) as executor:
        batch = executor.submit(gateway.execute_batch, [call("ONE"), call("TWO"), call("THREE")])
        assert entered.wait(10)
        try:
            with pytest.raises(ContractValidationError, match=r"batch"):
                gateway.execute(call("FOUR", batch="BATCH_TWO"))
        finally:
            release.set()
        results = batch.result(10)
    assert len(results) == 3 and peak == 2


def test_gate_stops_queued_call_without_billing_it(tmp_path, monkeypatch):
    from jobagent.connectors.mcp_gateway import McpReadGateway

    _, _, repo, _ = setup_round(tmp_path, monkeypatch, MCP_MAX_PARALLEL=1)
    called = []

    def runner(request, dispatched):
        dispatched()
        called.append(request.call_id)
        return provider("gate", error_code="429001")

    result = McpReadGateway(repo, runner, clock=lambda: NOW).execute_batch(
        [call("ONE"), call("TWO")]
    )
    assert [item.status for item in result] == ["gate", "not_called"]
    assert called == ["ONE"] and repo.status("MCP_ONE").actual_calls == 1
    assert "halted" in result[1].result.reason
