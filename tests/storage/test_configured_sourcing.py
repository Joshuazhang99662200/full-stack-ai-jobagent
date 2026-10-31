from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.rules.service import make_proposal
from jobagent.schemas.dynamic_rules import RuleConfirmation
from jobagent.schemas.sourcing import (
    ReadOutcome,
    ReadReservation,
    SourcingAttemptRequest,
    SourcingRunRequest,
)
from jobagent.storage.database import Database
from jobagent.storage.read_repository import SqliteReadRepository
from jobagent.storage.rule_repository import SqliteRuleRepository
from jobagent.storage.sourcing_repository import SqliteSourcingRepository
from tests.rules.test_dynamic_registry import request

NOW = datetime(2026, 10, 30, 9, tzinfo=UTC)


def configured(tmp_path, *, initialize=True, **changes):
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    db = Database(tmp_path / "configured.sqlite3")
    db.migrate()
    store = SqliteRuleRepository(db)
    current = None
    values = {
        "QUERIES_PER_SITE_PER_ROUND": 2,
        "TOP_PER_QUERY": 3,
        "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND": 2,
        "DETAIL_CAP_PER_DAY": 9,
    } | changes
    for index, (name, value) in enumerate(values.items()):
        at = NOW - timedelta(minutes=5) + timedelta(seconds=index)
        change = request(name, value)
        change.provenance.decided_at = at
        change.expected_version = current.version if current else None
        proposed = make_proposal(change, current, now=at)
        store.save_proposal(proposed)
        current = store.approve(
            RuleConfirmation(
                proposal_id=proposed.proposal_id,
                question_digest=proposed.question_digest,
                actor_id="synthetic owner",
                answer="Synthetic exact parameter approval",
                confirmed_at=at,
            ),
            candidate_id=change.candidate_id,
        )
    if initialize:
        SqliteConfigurationRepository(db).initialize(current.candidate_id, current.version, now=NOW)
    return db, current


def intent(rules, **changes):
    return SourcingRunRequest.model_validate(
        dict(
            run_id="RUN_SYNTH",
            candidate_id=rules.candidate_id,
            source="boss",
            rules_version=rules.version,
        )
        | changes
    )


def detail(attempt_id):
    return SourcingAttemptRequest(
        attempt_id=attempt_id,
        run_id="RUN_SYNTH",
        kind="detail",
        source_job_id="SYNTH_JOB",
        url="https://www.zhipin.com/job_detail/synthetic.html",
    )


def test_start_freezes_the_current_confirmed_values(tmp_path):
    db, rules = configured(tmp_path)
    run = SqliteSourcingRepository(db).start_run(intent(rules), now=NOW, daily_cap=9)
    assert (run.query_limit, run.detail_limit, run.top_per_query) == (2, 2, 3)
    assert run.rules_version == rules.version and run.daily_detail_limit == 9
    with pytest.raises(ContractValidationError, match=r"snapshot|configured|version"):
        SqliteSourcingRepository(db).start_run(
            SourcingRunRequest(run_id="BYPASS", candidate_id=rules.candidate_id, source="boss"),
            now=NOW,
            daily_cap=9,
        )


def test_confirmation_without_completed_initialization_cannot_start(tmp_path):
    db, rules = configured(tmp_path, initialize=False)
    with pytest.raises(ContractValidationError, match=r"initializ"):
        SqliteSourcingRepository(db).start_run(intent(rules), now=NOW, daily_cap=9)
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM sourcing_runs").fetchone()[0] == 0


def test_both_detail_entry_points_share_the_same_round_limit(tmp_path):
    db, rules = configured(tmp_path)
    repo = SqliteSourcingRepository(db)
    repo.start_run(intent(rules), now=NOW, daily_cap=9)
    assert repo.reserve(detail("ONE"), now=NOW).allowed
    reads = SqliteReadRepository(db)
    capture = ReadReservation(
        attempt_id="TWO",
        source="boss",
        target_url="https://www.zhipin.com/jobs/",
        profile="standard",
        expected_daily_cap=9,
        run_id="RUN_SYNTH",
        candidate_id=rules.candidate_id,
    )
    assert reads.reserve(capture, now=NOW, daily_cap=9).allowed
    reads.record(ReadOutcome(attempt_id="TWO", status="failed"), now=NOW)
    assert not reads.reserve(capture, now=NOW, daily_cap=9).allowed
    denied = repo.reserve(detail("THREE"), now=NOW)
    assert not denied.allowed and denied.reason == "round_detail_limit"
    with pytest.raises(ContractValidationError, match=r"round"):
        reads.reserve(capture.model_copy(update={"attempt_id": "FOUR"}), now=NOW, daily_cap=9)
    assert repo.budget("boss", daily_cap=9, now=NOW).read_today == 2


def test_initialized_profile_cannot_use_an_unbound_read_to_bypass_its_round(tmp_path):
    db, rules = configured(tmp_path)
    with pytest.raises(ContractValidationError, match=r"run|round"):
        SqliteReadRepository(db).reserve(
            ReadReservation(
                attempt_id="UNBOUND",
                source="boss",
                target_url="https://www.zhipin.com/jobs/",
                profile="standard",
                expected_daily_cap=9,
                candidate_id=rules.candidate_id,
            ),
            now=NOW,
            daily_cap=9,
        )


def saved_change(db, rules, *, scope="reusable", save=True):
    from jobagent.schemas.dynamic_rules import OwnerChangeRequest
    from jobagent.schemas.sourcing import ConfirmedRoundOverride

    at = NOW + timedelta(seconds=1)
    change = request("TOP_PER_QUERY", 2)
    change.expected_version = rules.version
    change.provenance.decided_at = at
    change.owner_request = OwnerChangeRequest(
        candidate_id=rules.candidate_id,
        names=[change.name],
        owner_text="Synthetic explicit change",
        source_reference="synthetic-owner-message",
        actor_id="synthetic owner",
        requested_at=at,
        scope=scope,
        run_id="RUN_SYNTH" if scope == "round" else None,
    )
    proposed = make_proposal(change, rules, now=at)
    if save:
        SqliteRuleRepository(db).save_proposal(proposed)
    return ConfirmedRoundOverride(
        proposal=proposed,
        confirmation=RuleConfirmation(
            proposal_id=proposed.proposal_id,
            question_digest=proposed.question_digest,
            actor_id="synthetic owner",
            answer="Synthetic exact change approval",
            confirmed_at=at,
        ),
    )


def test_explicit_round_override_is_bound_once_and_does_not_change_reusable_values(tmp_path):
    db, rules = configured(tmp_path)
    override = saved_change(db, rules, scope="round")
    repo = SqliteSourcingRepository(db)
    run = repo.start_run(
        intent(rules, round_overrides=[override]), now=NOW + timedelta(seconds=2), daily_cap=9
    )
    assert run.top_per_query == 2 and run.base_rules_version == rules.version
    assert run.rules_version != rules.version
    assert SqliteRuleRepository(db).current(rules.candidate_id).values["TOP_PER_QUERY"] == 3
    following = repo.start_run(
        intent(rules, run_id="RUN_NEXT"), now=NOW + timedelta(seconds=3), daily_cap=9
    )
    assert following.top_per_query == 3 and following.base_rules_version is None
    assert repo.reserve(detail("ROUND_OVERRIDE_READ"), now=NOW + timedelta(seconds=4)).allowed


def test_unsaved_round_question_cannot_be_used_as_execution_approval(tmp_path):
    db, rules = configured(tmp_path)
    override = saved_change(db, rules, scope="round", save=False)
    with pytest.raises(ContractValidationError, match=r"saved|question"):
        SqliteSourcingRepository(db).start_run(
            intent(rules, round_overrides=[override]), now=NOW + timedelta(seconds=2), daily_cap=9
        )


def test_rules_change_invalidates_new_reads_without_reopening_questions(tmp_path):
    db, rules = configured(tmp_path)
    repo = SqliteSourcingRepository(db)
    repo.start_run(intent(rules), now=NOW, daily_cap=9)
    change = saved_change(db, rules)
    SqliteRuleRepository(db).approve(change.confirmation, candidate_id=rules.candidate_id)
    with pytest.raises(ContractValidationError, match=r"version|snapshot|stale"):
        repo.reserve(detail("STALE_READ"), now=NOW + timedelta(seconds=2))
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM sourcing_attempts").fetchone()[0] == 0


def test_code_revision_change_blocks_a_prepared_round(tmp_path, monkeypatch):
    db, rules = configured(tmp_path)
    repo = SqliteSourcingRepository(db)
    run = repo.start_run(intent(rules), now=NOW, daily_cap=9)
    assert run.code_revision
    monkeypatch.setattr(
        "jobagent.storage.sourcing_repository.runtime_fingerprint", lambda: "sha256:" + "b" * 64
    )
    with pytest.raises(ContractValidationError, match=r"code|runtime"):
        repo.reserve(detail("OLD_CODE"), now=NOW)


def test_confirmed_daily_cap_is_not_silently_lowered(tmp_path):
    db, rules = configured(tmp_path)
    with pytest.raises(ContractValidationError, match=r"cap|policy"):
        SqliteSourcingRepository(db).start_run(intent(rules), now=NOW, daily_cap=8)


def test_used_round_intent_cannot_reopen_configuration_questions(tmp_path):
    from jobagent.schemas.configuration import ConfigurationPreparationRequest
    from jobagent.storage.configuration_repository import SqliteConfigurationRepository

    db, rules = configured(tmp_path)
    override = saved_change(db, rules, scope="round")
    at = NOW + timedelta(seconds=2)
    SqliteSourcingRepository(db).start_run(
        intent(rules, round_overrides=[override]), now=at, daily_cap=9
    )
    result = SqliteConfigurationRepository(db).prepare(
        ConfigurationPreparationRequest(
            candidate_id=rules.candidate_id,
            task_id="TASK_OTHER",
            task_type="another-type",
            mode="owner_requested_change",
            owner_request=override.proposal.request.owner_request,
        ),
        now=at,
    )
    assert not result.ask_user and result.questions == []
