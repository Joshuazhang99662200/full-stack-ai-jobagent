from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.rules.service import make_proposal
from jobagent.schemas.dynamic_rules import RuleConfirmation
from jobagent.storage.database import Database
from jobagent.storage.rule_repository import SqliteRuleRepository
from tests.rules.test_dynamic_registry import request
from tests.rules.test_preparation import BASE_VALUES, owner_request, preparation

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def confirm(repository, name, value, *, at=NOW, authorization=None):
    current = repository.current("CAND_SYNTHETIC")
    change = request(name, value)
    change.expected_version = current.version if current else None
    change.provenance.decided_at = at
    if authorization is not None:
        change.owner_request = authorization
    proposal = make_proposal(change, current, now=at)
    repository.save_proposal(proposal)
    return repository.approve(RuleConfirmation(
        proposal_id=proposal.proposal_id, question_digest=proposal.question_digest,
        answer="Synthetic exact configuration approval", actor_id="synthetic owner",
        confirmed_at=at,
    ), candidate_id="CAND_SYNTHETIC")


def configured(tmp_path):
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    db = Database(tmp_path / "configuration.sqlite3")
    db.migrate()
    rules = SqliteRuleRepository(db)
    for index, (name, value) in enumerate(BASE_VALUES.items()):
        current = confirm(rules, name, value, at=NOW + timedelta(seconds=index))
    configuration = SqliteConfigurationRepository(db)
    configuration.initialize("CAND_SYNTHETIC", current.version, now=NOW + timedelta(seconds=4))
    return db, rules, configuration, current


def test_prepare_does_not_create_a_database_or_consume_reads(tmp_path):
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    path = tmp_path / "missing" / "configuration.sqlite3"
    result = SqliteConfigurationRepository(Database(path)).prepare(preparation("initial_setup"))
    assert result.ask_user and not path.exists() and not path.parent.exists()


def test_initialized_marker_is_stable_and_readonly_across_sessions(tmp_path):
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    db, _, configuration, snapshot = configured(tmp_path)
    before = db.path.read_bytes()
    for kind in ["sourcing", "new-type", "restored-session"]:
        result = SqliteConfigurationRepository(db).prepare(
            preparation("initial_setup").model_copy(update={"task_type": kind}),
        )
        assert result.ready and result.initialized and not result.ask_user
    assert db.path.read_bytes() == before
    again = configuration.initialize("CAND_SYNTHETIC", snapshot.version,
                                     now=NOW + timedelta(seconds=5))
    assert again.initialized_at == NOW + timedelta(seconds=4)


def test_initialization_requires_current_complete_confirmed_profile(tmp_path):
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    db = Database(tmp_path / "incomplete.sqlite3")
    db.migrate()
    rules = SqliteRuleRepository(db)
    snapshot = confirm(rules, "TOP_PER_QUERY", 7)
    config = SqliteConfigurationRepository(db)
    with pytest.raises(ContractValidationError, match="missing"):
        config.initialize("CAND_SYNTHETIC", snapshot.version, now=NOW)
    with pytest.raises(ContractValidationError, match=r"current|stale"):
        config.initialize("CAND_SYNTHETIC", "sha256:old", now=NOW)


def test_initialized_changes_need_explicit_matching_owner_request(tmp_path):
    _, rules, _, snapshot = configured(tmp_path)
    later = NOW + timedelta(days=1)
    change = request("TOP_PER_QUERY", 9)
    change.expected_version = snapshot.version
    change.provenance.decided_at = later
    proposal = make_proposal(change, snapshot, now=later)
    with pytest.raises(ContractValidationError, match="owner request"):
        rules.save_proposal(proposal)
    assert rules.current("CAND_SYNTHETIC").version == snapshot.version
    updated = confirm(rules, "TOP_PER_QUERY", 9, at=later,
                      authorization=owner_request(requested_at=later))
    assert updated.values["TOP_PER_QUERY"] == 9
    assert updated.values["DETAIL_ATTEMPTS_PER_SITE_PER_ROUND"] == 19


def test_proposal_saved_before_initialization_cannot_bypass_owner_request_on_approve(tmp_path):
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    db = Database(tmp_path / "race.sqlite3")
    db.migrate()
    rules = SqliteRuleRepository(db)
    for index, (name, value) in enumerate(BASE_VALUES.items()):
        current = confirm(rules, name, value, at=NOW + timedelta(seconds=index))
    later = NOW + timedelta(seconds=5)
    change = request("TOP_PER_QUERY", 9)
    change.expected_version = current.version
    change.provenance.decided_at = later
    proposal = make_proposal(change, current, now=later)
    rules.save_proposal(proposal)
    SqliteConfigurationRepository(db).initialize("CAND_SYNTHETIC", current.version,
                                               now=later + timedelta(seconds=1))
    with pytest.raises(ContractValidationError, match="owner request"):
        rules.approve(RuleConfirmation(
            proposal_id=proposal.proposal_id, question_digest=proposal.question_digest,
            answer="Synthetic approval", actor_id="synthetic owner",
            confirmed_at=later + timedelta(seconds=2),
        ), candidate_id="CAND_SYNTHETIC")


def test_round_only_confirmation_cannot_update_reusable_head(tmp_path):
    _, rules, _, current = configured(tmp_path)
    later = NOW + timedelta(days=1)
    change = request("TOP_PER_QUERY", 4)
    change.expected_version = current.version
    change.provenance.decided_at = later
    change.owner_request = owner_request(requested_at=later, scope="round", run_id="SYNTH_RUN")
    proposal = make_proposal(change, current, now=later)
    rules.save_proposal(proposal)
    with pytest.raises(ContractValidationError, match="round"):
        rules.approve(RuleConfirmation(
            proposal_id=proposal.proposal_id, question_digest=proposal.question_digest,
            answer="Synthetic round-only approval", actor_id="synthetic owner", confirmed_at=later,
        ), candidate_id="CAND_SYNTHETIC")
    assert rules.current("CAND_SYNTHETIC").version == current.version


def test_upgrade_preserves_existing_profiles_without_reopening_setup(tmp_path):
    import sqlite3
    from importlib import resources

    from jobagent.storage.configuration_repository import SqliteConfigurationRepository
    from jobagent.storage.database import _MIGRATION_FILES

    db = Database(tmp_path / "previous.sqlite3")
    with db.connect() as connection:
        for number in range(1, 31):
            connection.executescript(resources.files("jobagent.storage.migrations").joinpath(
                _MIGRATION_FILES[number],
            ).read_text(encoding="utf-8"))
    rules = SqliteRuleRepository(db)
    confirm(rules, "ABANDON_HOURS", 73)
    db.migrate()
    result = SqliteConfigurationRepository(db).prepare(preparation("initial_setup"))
    assert result.initialized and not result.ask_user and result.questions == []
    assert not result.ready and result.status == "blocked_by_missing_configuration"
    with db.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM configuration_initializations")


def test_consumed_owner_message_cannot_reopen_form_or_authorize_a_later_proposal(tmp_path):
    _, rules, config, _ = configured(tmp_path)
    at = NOW + timedelta(days=1)
    authorization = owner_request(requested_at=at)
    current = confirm(rules, "TOP_PER_QUERY", 9, at=at, authorization=authorization)
    form = config.prepare(preparation("owner_requested_change", owner_request=authorization),
                          now=at + timedelta(hours=1))
    assert not form.ask_user and form.questions == [] and not form.ready
    assert form.status == "blocked_by_conflict"
    for owner_at in [at, at + timedelta(hours=1)]:
        change = request("TOP_PER_QUERY", 12)
        change.expected_version = current.version
        change.provenance.decided_at = at + timedelta(hours=2)
        change.owner_request = authorization.model_copy(update={"requested_at": owner_at})
        proposal = make_proposal(change, current, now=change.provenance.decided_at)
        with pytest.raises(ContractValidationError, match="consum"):
            rules.save_proposal(proposal)
    changed_date = authorization.model_copy(update={"requested_at": at + timedelta(hours=1)})
    repeated = config.prepare(preparation("owner_requested_change", owner_request=changed_date),
                              now=at + timedelta(hours=2))
    assert not repeated.ask_user and repeated.questions == []


def test_multi_name_owner_message_consumes_only_approved_field_and_replay_is_idempotent(tmp_path):
    db, rules, config, _ = configured(tmp_path)
    at = NOW + timedelta(days=1)
    authorization = owner_request(
        requested_at=at, names=["TOP_PER_QUERY", "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND"],
    )
    updated = confirm(rules, "TOP_PER_QUERY", 9, at=at, authorization=authorization)
    form = config.prepare(preparation("owner_requested_change", owner_request=authorization),
                          now=at + timedelta(seconds=1))
    assert form.ask_user and len(form.questions) == 1
    assert "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND" in form.questions[0]
    with db.connect() as connection:
        raw = connection.execute(
            "SELECT confirmation_json FROM dynamic_rule_confirmations WHERE version=?",
            (updated.version,),
        ).fetchone()[0]
    assert rules.approve(RuleConfirmation.model_validate_json(raw),
                         candidate_id=updated.candidate_id) == updated
    confirm(rules, "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND", 11,
            at=at + timedelta(seconds=2), authorization=authorization)
    finished = config.prepare(preparation("owner_requested_change", owner_request=authorization),
                              now=at + timedelta(seconds=3))
    assert not finished.ask_user and finished.questions == []
    with db.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM configuration_owner_consumptions",
        ).fetchone()[0]
        assert count == 2


def test_round_consumption_allows_only_exact_same_event_and_proposal_revalidation(tmp_path):
    from jobagent.storage.configuration_repository import (
        consume_owner_change_request,
        require_owner_change_request,
    )

    db, rules, _, current = configured(tmp_path)
    at = NOW + timedelta(days=1)
    change = request("TOP_PER_QUERY", 4)
    change.expected_version = current.version
    change.provenance.decided_at = at
    change.owner_request = owner_request(requested_at=at, scope="round", run_id="SYNTH_RUN")
    proposal = make_proposal(change, current, now=at)
    rules.save_proposal(proposal)
    with db.connect() as connection, connection:
        consume_owner_change_request(connection, proposal, event_id="SYNTH_RUN")
        consume_owner_change_request(connection, proposal, event_id="SYNTH_RUN")
        require_owner_change_request(connection, proposal, allow_consumed_by="SYNTH_RUN")
        with pytest.raises(ContractValidationError, match="consum"):
            require_owner_change_request(connection, proposal, allow_consumed_by="ANOTHER_RUN")
    other_change = change.model_copy(deep=True)
    other_change.value = 5
    another = make_proposal(other_change, current, now=at + timedelta(seconds=1))
    with db.connect() as connection, pytest.raises(ContractValidationError, match="consum"):
        require_owner_change_request(connection, another, allow_consumed_by="SYNTH_RUN")


@pytest.mark.parametrize("original_scope", ["reusable", "round"])
def test_consumed_message_cannot_be_reopened_by_changing_scope_or_round(tmp_path, original_scope):
    from jobagent.storage.configuration_repository import consume_owner_change_request

    db, rules, config, current = configured(tmp_path)
    at = NOW + timedelta(days=1)
    authorization = owner_request(
        requested_at=at, scope=original_scope,
        run_id="ROUND_A" if original_scope == "round" else None,
    )
    if original_scope == "reusable":
        current = confirm(rules, "TOP_PER_QUERY", 9, at=at, authorization=authorization)
    else:
        change = request("TOP_PER_QUERY", 9)
        change.expected_version = current.version
        change.provenance.decided_at = at
        change.owner_request = authorization
        original = make_proposal(change, current, now=at)
        rules.save_proposal(original)
        with db.connect() as connection, connection:
            consume_owner_change_request(connection, original, event_id="ROUND_A")
    changed = authorization.model_copy(update={
        "scope": "round", "run_id": "ROUND_B", "requested_at": at + timedelta(hours=1),
    })
    another = request("TOP_PER_QUERY", 12)
    another.expected_version = current.version
    another.provenance.decided_at = changed.requested_at
    another.owner_request = changed
    proposal = make_proposal(another, current, now=changed.requested_at)
    with pytest.raises(ContractValidationError, match="consum"):
        rules.save_proposal(proposal)
    form = config.prepare(preparation("owner_requested_change", owner_request=changed),
                          now=changed.requested_at)
    assert not form.ask_user and form.questions == []
