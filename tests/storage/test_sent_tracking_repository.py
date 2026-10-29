from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.storage.database import Database
from tests.jobs.test_sent_tracking import NOW, event, proof


def repo(tmp_path):
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository

    database = Database(tmp_path / "tracking.sqlite3")
    database.migrate()
    return SqliteSentTrackingRepository(database)


def start(store):
    return store.start(proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_DEMO", now=NOW)


def test_start_and_event_replay_are_idempotent_without_storing_message_text(tmp_path):
    from tests.jobs.test_sent_tracking import TEXT

    store = repo(tmp_path)
    value = start(store)
    assert start(store) == value
    update = event(value, "no_reply")
    changed = store.apply(update, now=update.observed_at)
    assert store.apply(update, now=update.observed_at) == changed
    assert len(store.history(value.tracking_id, "CAND_DEMO")) == 3
    assert TEXT not in str(
        [row.model_dump() for row in store.history(value.tracking_id, "CAND_DEMO")]
    )
    with pytest.raises(ContractValidationError):
        store.apply(
            update.model_copy(update={"evidence_reference": "CHANGED"}), now=update.observed_at
        )


def test_optimistic_concurrency_allows_only_one_new_version(tmp_path):
    store = repo(tmp_path)
    value = start(store)

    def apply(number):
        update = event(value, "no_reply", event_id=f"EV_{number}", observation_id=f"OBS_{number}")
        try:
            store.apply(update, now=update.observed_at)
            return True
        except ContractValidationError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(apply, [1, 2])) == 1


def test_candidate_scope_due_filter_and_closed_history_are_preserved(tmp_path):
    store = repo(tmp_path)
    value = start(store)
    assert store.due("CAND_DEMO", now=NOW) == []
    assert len(store.due("CAND_DEMO", now=NOW + timedelta(days=1))) == 1
    assert store.due("CAND_OTHER", now=NOW + timedelta(days=1)) == []
    with pytest.raises(ContractValidationError):
        store.get(value.tracking_id, "CAND_OTHER")
    closed = store.apply(
        event(value, "user_abandon", evidence_kind="owner_message", owner_text="明确放弃"),
        now=NOW + timedelta(days=1),
    )
    assert closed.tracking_state.value == "closed"
    assert store.due("CAND_DEMO", now=NOW + timedelta(days=30)) == []
    assert len(store.history(value.tracking_id, "CAND_DEMO")) == 4


def test_an_audit_can_start_only_one_tracking_record(tmp_path):
    store = repo(tmp_path)
    start(store)
    with pytest.raises(ContractValidationError):
        store.start(proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_ANOTHER", now=NOW)


def activate_pipeline(store, candidate="CAND_DEMO"):
    with store.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO pipeline_authorities VALUES (?, ?, ?)",
            (candidate, NOW.isoformat(), "PRIVATE_SWITCH_RECEIPT"),
        )


def test_pipeline_authority_blocks_old_mutations_but_preserves_history_reading(tmp_path):
    store = repo(tmp_path)
    value = start(store)
    before = store.history(value.tracking_id, value.candidate_id)
    activate_pipeline(store)
    with pytest.raises(ContractValidationError, match="pipeline"):
        start(store)
    with pytest.raises(ContractValidationError, match="pipeline"):
        store.apply(event(value, "no_reply"), now=NOW + timedelta(days=1))
    assert store.due(value.candidate_id, now=NOW + timedelta(days=1)) == []
    assert store.get(value.tracking_id, value.candidate_id) == value
    assert store.list_records(value.candidate_id) == [value]
    assert store.history(value.tracking_id, value.candidate_id) == before


def test_authority_switch_is_candidate_scoped(tmp_path):
    store = repo(tmp_path)
    activate_pipeline(store, candidate="CAND_OTHER")
    assert start(store).candidate_id == "CAND_DEMO"


def test_due_caps_persisted_legacy_schedule_at_real_deadline(tmp_path):
    store = repo(tmp_path)
    value = start(store)
    previous = store.history(value.tracking_id, value.candidate_id)[-1]
    legacy_state = value.model_copy(
        update={"next_check_at": NOW + timedelta(days=7), "tracking_version": 3}
    )
    legacy_event = previous.model_copy(
        update={"event_id": "LEGACY_SCHEDULE", "version": 3, "state": legacy_state}
    )
    with store.database.connect() as connection, connection:
        store._append(connection, [legacy_event])
    assert store.due(value.candidate_id, now=NOW + timedelta(hours=47)) == []
    assert store.due(value.candidate_id, now=NOW + timedelta(hours=48)) == [legacy_state]
