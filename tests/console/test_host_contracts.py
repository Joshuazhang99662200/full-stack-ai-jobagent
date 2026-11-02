import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_positive_execution_result_requires_readback_bound_to_material():
    from jobagent.schemas.console_host import HostReadback

    with pytest.raises(ValidationError):
        HostReadback(status="verified", detail="A display label is not evidence")
    value = HostReadback(
        status="verified",
        detail="Synthetic platform readback",
        evidence="SYNTHETIC_READBACK",
        material_revision="REV_A",
        observed_at="2026-11-02T10:00:00+08:00",
    )
    assert value.status == "verified"


def test_decision_binds_candidate_round_version_and_deduplication_key():
    from jobagent.schemas.console_host import HostDecisionRequest

    with pytest.raises(ValidationError):
        HostDecisionRequest(kind="approve_material", body="example")
    value = HostDecisionRequest(
        candidate_id="CAND_DEMO",
        job_id="DEMO_A",
        contact_id="PIPE_AAAAAAAAAAAAAAAA",
        operation_key="OP_EXAMPLE",
        kind="approve_material",
        material_revision="REV_A",
        body="Exact synthetic text",
        attachment_digests=[],
        note="",
    )
    assert value.operation_key == "OP_EXAMPLE"
    assert "send" not in value.model_dump()


def test_personal_todo_requires_actionable_options_and_evidence():
    from jobagent.schemas.console_host import HostTodo

    with pytest.raises(ValidationError):
        HostTodo(
            todo_id="TODO_A", job_id="DEMO_A", contact_id="PIPE_A", question="Missing JD",
            material_revision="REV_A", requires_person=True, host_resolved=True,
            basis=[], options=[], status="pending", result=None,
        )


def test_typescript_contracts_match_authoritative_python_schema():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/build_console_host_contracts.py", "--check"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
