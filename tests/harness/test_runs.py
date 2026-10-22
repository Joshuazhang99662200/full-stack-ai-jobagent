from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.harness.service import HarnessService
from jobagent.schemas.harness import RunPhase


def test_run_handoff_keeps_identity_and_rejects_active_other_host(tmp_path):
    service = HarnessService(tmp_path)
    run = service.start("CAND_001", "codex", "a")
    with pytest.raises(ContractValidationError, match="lease"):
        service.resume(run.run_id, "claude-code", "b")
    service.checkpoint(run.run_id, "a", RunPhase.WAITING_FOR_LOGIN)
    service.release(run.run_id, "a")
    resumed = service.resume(run.run_id, "claude-code", "b")
    assert resumed.run_id == run.run_id
    assert resumed.phase == RunPhase.WAITING_FOR_LOGIN
    assert resumed.host == "claude-code"
    assert not hasattr(resumed, "approval")


def test_checkpoint_requires_owner_and_terminal_cannot_resume(tmp_path):
    service = HarnessService(tmp_path)
    run = service.start("CAND_001", "codex", "a")
    with pytest.raises(ContractValidationError, match="lease"):
        service.checkpoint(run.run_id, "b", RunPhase.COMPLETED)
    service.checkpoint(run.run_id, "a", RunPhase.CANCELLED)
    service.release(run.run_id, "a")
    with pytest.raises(ContractValidationError, match="terminal"):
        service.resume(run.run_id, "codex", "a")


def test_expired_lease_requires_explicit_recovery(tmp_path):
    now = datetime.now(UTC)
    service = HarnessService(tmp_path, clock=lambda: now, lease_seconds=5)
    run = service.start("CAND_001", "codex", "a")
    now += timedelta(seconds=6)
    with pytest.raises(ContractValidationError, match="recover"):
        service.resume(run.run_id, "claude-code", "b")
    assert service.resume(run.run_id, "claude-code", "b", recover=True).session_id == "b"


def test_artifact_contract_and_digest_survive_resume(tmp_path):
    service = HarnessService(tmp_path)
    run = service.start("CAND_001", "codex", "a")
    path = tmp_path / "base.json"
    path.write_text('{"id":"base","language":"en","source_digest":"sha256:abc"}')
    service.checkpoint(run.run_id, "a", RunPhase.WAITING_FOR_REVIEW, path, "BaseResumeDocument")
    service.release(run.run_id, "a")
    path.write_text("{}")
    with pytest.raises(ContractValidationError, match="changed"):
        service.resume(run.run_id, "codex", "a")


def test_artifact_rejects_invalid_contract_and_workspace_escape(tmp_path):
    service = HarnessService(tmp_path)
    run = service.start("CAND_001", "codex", "a")
    path = tmp_path / "invalid.json"
    path.write_text("{}")
    with pytest.raises(ContractValidationError, match="contract"):
        service.checkpoint(run.run_id, "a", RunPhase.RUNNING, path, "BaseResumeDocument")
    with pytest.raises(ContractValidationError, match="workspace"):
        service.checkpoint(
            run.run_id, "a", RunPhase.RUNNING, tmp_path.parent / "outside.json", "PDF"
        )
    with pytest.raises(ContractValidationError):
        service.status("../../outside")


def test_run_ids_are_unique_and_lock_prevents_lost_update(tmp_path):
    service = HarnessService(tmp_path)
    a = service.start("CAND_001", "codex", "a")
    b = service.start("CAND_001", "codex", "a")
    assert a.run_id != b.run_id
    lock = tmp_path / ".jobagent/runs" / a.run_id / "state.lock"
    lock.write_text("locked")
    with pytest.raises(ContractValidationError, match="locked"):
        service.release(a.run_id, "a")


def test_changed_runtime_cannot_resume_even_with_recover(tmp_path):
    service = HarnessService(tmp_path, runtime_digest="sha256:release-a")
    run = service.start("CAND_001", "codex", "a")
    service.release(run.run_id, "a")
    upgraded = HarnessService(tmp_path, runtime_digest="sha256:release-b")
    with pytest.raises(ContractValidationError, match="runtime"):
        upgraded.resume(run.run_id, "claude-code", "b", recover=True)
