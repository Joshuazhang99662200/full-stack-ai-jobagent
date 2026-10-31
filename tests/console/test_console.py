import json
from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.harness import HarnessRun, RunPhase
from tests.storage.test_pipeline import create, repo

NOW = datetime(2026, 10, 31, 3, tzinfo=UTC)
RUN = "RUN_" + "A" * 32


def setup_run(tmp_path):
    directory = tmp_path / ".jobagent/runs" / RUN
    directory.mkdir(parents=True)
    run = HarnessRun(
        run_id=RUN,
        candidate_id="CAND_DEMO",
        runtime_digest="sha256:synthetic",
        host="codex",
        created_at=NOW,
        updated_at=NOW,
        phase="running",
    )
    (directory / "state.json").write_text(run.model_dump_json(), encoding="utf-8")
    return run


def test_missing_database_is_not_created_or_reported_as_complete(tmp_path):
    from jobagent.console.projection import snapshot

    database = tmp_path / "absent.sqlite3"
    result = snapshot(database, tmp_path, "CAND_DEMO", now=NOW)
    assert not database.exists()
    assert result.jobs == []
    assert next(s for s in result.sources if s.name == "pipeline").status == "missing"


def test_projection_preserves_fields_history_scope_and_database_bytes(tmp_path):
    from jobagent.console.projection import definitions, snapshot
    from jobagent.jobs.jd_snapshot import text_digest

    store = repo(tmp_path)
    text = "Synthetic full JD <script>external data</script>"
    job, meta = create(store, jd_text=text, jd_text_hash=text_digest(text))
    other = job.model_copy(
        update={"candidate_id": "CAND_OTHER", "pipeline_id": "PIPE_BBBBBBBBBBBBBBBB"}
    )
    store.create(
        other,
        meta.model_copy(update={"pipeline_id": other.pipeline_id}),
        event_id="OTHER_CREATE",
        evidence_reference="ENTRY",
    )
    before = store.database.path.read_bytes()
    result = snapshot(store.database.path, tmp_path, job.candidate_id, now=NOW)
    assert len(result.jobs) == 1
    assert result.jobs[0].job == job and result.jobs[0].meta == meta
    assert result.jobs[0].history == store.history(job.pipeline_id, job.candidate_id)
    assert store.database.path.read_bytes() == before
    assert "jd_text" in json.dumps(definitions())


def test_corrupt_database_and_harness_are_diagnostics(tmp_path):
    from jobagent.console.projection import snapshot

    database = tmp_path / "corrupt.sqlite3"
    database.write_text("corrupt", encoding="utf-8")
    directory = tmp_path / ".jobagent/runs" / RUN
    directory.mkdir(parents=True)
    (directory / "state.json").write_text("not json", encoding="utf-8")
    result = snapshot(database, tmp_path, "CAND_DEMO", now=NOW)
    assert next(s for s in result.sources if s.name == "pipeline").status == "invalid"
    assert next(s for s in result.sources if s.name == "harness").status == "invalid"


def event(**changes):
    from jobagent.schemas.console import ConsoleActivityInput

    data = dict(
        event_id="EV_SYNTHETIC",
        candidate_id="CAND_DEMO",
        run_id=RUN,
        activity_id="ACT_SYNTHETIC",
        activity="fetch",
        status="started",
        occurred_at=NOW,
        owner="synthetic host",
    )
    data.update(changes)
    return ConsoleActivityInput.model_validate(data)


def test_activity_is_idempotent_owned_and_does_not_mutate_run(tmp_path):
    from jobagent.console.activities import record_activity
    from jobagent.console.projection import snapshot

    setup_run(tmp_path)
    path = tmp_path / ".jobagent/runs" / RUN / "state.json"
    before = path.read_bytes()
    first = record_activity(tmp_path, event(), now=NOW)
    assert record_activity(tmp_path, event(), now=NOW + timedelta(seconds=1)) == first
    with pytest.raises(ContractValidationError):
        record_activity(tmp_path, event(owner="changed"), now=NOW)
    with pytest.raises(ContractValidationError):
        record_activity(tmp_path, event(candidate_id="CAND_OTHER"), now=NOW)
    assert path.read_bytes() == before
    result = snapshot(
        tmp_path / "missing.sqlite3", tmp_path, "CAND_DEMO", now=NOW + timedelta(hours=1)
    )
    assert result.runs[0].freshness == "stale"
    assert result.runs[0].activities == [first]
    assert snapshot(tmp_path / "missing.sqlite3", tmp_path, "CAND_OTHER", now=NOW).runs == []


def test_activity_rejects_missing_start_time_reversal_and_terminal_resume(tmp_path):
    from jobagent.console.activities import record_activity

    setup_run(tmp_path)
    with pytest.raises(ContractValidationError):
        record_activity(tmp_path, event(status="completed"), now=NOW)
    record_activity(tmp_path, event(), now=NOW)
    with pytest.raises(ContractValidationError):
        record_activity(
            tmp_path,
            event(event_id="BACKWARDS", status="heartbeat", occurred_at=NOW - timedelta(seconds=1)),
            now=NOW,
        )
    record_activity(tmp_path, event(event_id="FINISH", status="completed"), now=NOW)
    with pytest.raises(ContractValidationError):
        record_activity(tmp_path, event(event_id="RESTART", status="heartbeat"), now=NOW)


def test_activity_requires_aware_time_and_disallows_path_identity():
    with pytest.raises(ValueError):
        event(occurred_at=datetime(2026, 10, 31))
    with pytest.raises(ValueError):
        event(run_id="../../state")


def test_terminal_run_cannot_gain_activity_and_missing_stages_stay_unknown(tmp_path):
    from jobagent.console.activities import record_activity
    from jobagent.console.projection import snapshot

    run = setup_run(tmp_path)
    result = snapshot(tmp_path / "missing.sqlite3", tmp_path, "CAND_DEMO", now=NOW)
    assert result.runs[0].freshness == "unknown"
    assert next(s for s in result.sources if s.name == "activities").status == "missing"
    path = tmp_path / ".jobagent/runs" / RUN / "state.json"
    path.write_text(
        run.model_copy(update={"phase": RunPhase.COMPLETED}).model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(ContractValidationError):
        record_activity(tmp_path, event(), now=NOW)


def test_tampered_activity_ownership_prevents_append(tmp_path):
    from jobagent.console.activities import record_activity

    setup_run(tmp_path)
    record_activity(tmp_path, event(), now=NOW)
    path = tmp_path / ".jobagent/runs" / RUN / "console-activities.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[0]["candidate_id"] = "CAND_OTHER"
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ContractValidationError):
        record_activity(tmp_path, event(event_id="NEXT", status="heartbeat"), now=NOW)
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["corrupt", "future"])
def test_invalid_activities_keep_valid_harness_without_claiming_freshness(tmp_path, kind):
    from jobagent.console.activities import record_activity
    from jobagent.console.projection import snapshot

    setup_run(tmp_path)
    record_activity(tmp_path, event(), now=NOW)
    path = tmp_path / ".jobagent/runs" / RUN / "console-activities.json"
    if kind == "corrupt":
        path.write_text("corrupt", encoding="utf-8")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        data[0]["recorded_at"] = (NOW + timedelta(days=1)).isoformat()
        path.write_text(json.dumps(data), encoding="utf-8")
    result = snapshot(tmp_path / "absent.sqlite3", tmp_path, "CAND_DEMO", now=NOW)
    assert len(result.runs) == 1
    assert result.runs[0].freshness == "unknown" and result.runs[0].activities == []
    assert next(s for s in result.sources if s.name == "harness").status == "complete"
    assert next(s for s in result.sources if s.name == "activities").status == "invalid"
