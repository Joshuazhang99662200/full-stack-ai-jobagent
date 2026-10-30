# ruff: noqa: RUF001 -- Preserve synthetic Chinese source punctuation.
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError

NOW = datetime(2026, 10, 28, 8, tzinfo=UTC)


def request(**changes):
    from jobagent.schemas.job_intake import IntakeRequest

    data = dict(
        request_id="REQ_ONE",
        candidate_id="CAND_DEMO",
        domain="design",
        platform="boss",
        message_reference="CHAT_MSG_ONE",
        entry_kind="url",
        target_reference="https://example.com/jobs/one",
        job_url="https://example.com/jobs/one",
        intent="draft",
        job_preference="like",
        owner_text="这是我想投的方向，请加入目标岗位",
        occurred_at=NOW,
    )
    data.update(changes)
    return IntakeRequest.model_validate(data)


def repository(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.job_intake_repository import SqliteJobIntakeRepository

    tmp_path.mkdir(parents=True, exist_ok=True)
    db = Database(tmp_path / "private.sqlite3")
    db.migrate()
    return SqliteJobIntakeRepository(db)


def test_entry_contract_preserves_ambiguous_target_until_resolved():
    from jobagent.jobs.job_intake import next_actions

    with pytest.raises(ValueError):
        request(entry_kind="list_item", job_url=None, target_reference="35")
    item = request(
        entry_kind="list_item", job_url=None, target_reference="35", list_version="LIST_ONE"
    )
    assert item.list_version == "LIST_ONE"
    with pytest.raises(ValueError):
        request(owner_text="")
    assert next_actions


def test_enqueue_replay_and_same_target_add_new_source_without_new_job(tmp_path):
    from jobagent.jobs.job_intake import next_actions

    repo = repository(tmp_path)
    first = repo.enqueue(request(), now=NOW)
    replay = repo.enqueue(request(), now=NOW)
    assert first == replay
    assert next_actions(first) == ["resolve_target"]
    second = repo.enqueue(
        request(request_id="REQ_TWO", message_reference="CARD_TWO", entry_kind="conversation_card"),
        now=NOW,
    )
    assert second.intake_id == first.intake_id and second.version == first.version + 1
    assert len(repo.list_records("CAND_DEMO", "design")) == 1
    assert len(second.requests) == 2
    assert len(repo.history(first.intake_id, "CAND_DEMO")) == 2
    with pytest.raises(ContractValidationError):
        repo.enqueue(request(owner_text="conflicting replay"), now=NOW)
    with pytest.raises(ContractValidationError):
        repo.get(first.intake_id, "CAND_OTHER")


def test_unknown_number_does_not_alias_same_number_in_another_list(tmp_path):
    repo = repository(tmp_path)
    a = repo.enqueue(
        request(
            entry_kind="list_item", job_url=None, target_reference="35", list_version="LIST_ONE"
        ),
        now=NOW,
    )
    b = repo.enqueue(
        request(
            request_id="REQ_TWO",
            entry_kind="list_item",
            job_url=None,
            target_reference="35",
            list_version="LIST_TWO",
        ),
        now=NOW,
    )
    assert a.intake_id != b.intake_id


def test_cas_and_request_replay_survive_reopen(tmp_path):
    repo = repository(tmp_path)
    row = repo.enqueue(request(), now=NOW)
    args = dict(
        event_id="EV_PAUSE",
        expected_version=row.version,
        kind="pause",
        changes={"paused": True},
        now=NOW,
    )
    changed = repo.update(row.intake_id, row.candidate_id, **args)
    assert repository(tmp_path).get(row.intake_id, row.candidate_id) == changed
    assert repo.update(row.intake_id, row.candidate_id, **args) == changed
    with pytest.raises(ContractValidationError):
        repo.update(
            row.intake_id,
            row.candidate_id,
            event_id="EV_STALE",
            expected_version=row.version,
            kind="close",
            changes={"closed": True},
            now=NOW,
        )
    with pytest.raises(ContractValidationError):
        repo.update(row.intake_id, row.candidate_id, **{**args, "changes": {"paused": False}})


def test_two_workers_cannot_overwrite_the_same_version(tmp_path):
    repo = repository(tmp_path)
    row = repo.enqueue(request(), now=NOW)

    def compete(number):
        try:
            repo.update(
                row.intake_id,
                row.candidate_id,
                event_id=f"EV_{number}",
                expected_version=row.version,
                kind="pause",
                changes={"paused": True},
                now=NOW,
            )
            return True
        except ContractValidationError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(compete, [1, 2])) == 1


def test_dual_branches_do_not_block_greeting_on_lexicon_cold_start(tmp_path):
    from jobagent.jobs.job_intake import next_actions

    repo = repository(tmp_path)
    row = repo.enqueue(request(), now=NOW)
    row = repo.update(
        row.intake_id,
        row.candidate_id,
        event_id="EV_RESOLVE",
        expected_version=row.version,
        kind="resolve",
        changes={"job_id": "JOB_DEMO_1"},
        now=NOW,
    )
    assert next_actions(row) == ["fetch_full_jd"]
    row = repo.update(
        row.intake_id,
        row.candidate_id,
        event_id="EV_SNAPSHOT",
        expected_version=row.version,
        kind="snapshot",
        changes={
            "snapshot_id": "SNAP_ONE",
            "snapshot_version": 1,
            "jd_text_hash": "sha256:synthetic",
        },
        now=NOW,
    )
    assert set(next_actions(row)) == {"factorize", "generate_greeting"}
    assert next_actions(row.model_copy(update={"paused": True})) == ["owner_resume"]
    assert next_actions(row.model_copy(update={"closed": True})) == []
