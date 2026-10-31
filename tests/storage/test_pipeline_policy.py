from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.rules.service import make_proposal
from jobagent.schemas.dynamic_rules import RuleConfirmation
from jobagent.schemas.pipeline import PipelineObservation, PipelineVerifiedEvidence
from jobagent.storage.rule_repository import SqliteRuleRepository
from tests.jobs.test_pipeline_contracts import NOW
from tests.rules.test_dynamic_registry import request
from tests.storage.test_pipeline import command, create, repo

STATE_POLICY = {
    "ABANDON_HOURS": 48,
    "ABANDON_IMMEDIATE_REASONS": ["employer_rejected", "job_closed", "user_abandoned"],
    "RESUME_STAGE_IN_ABANDON_LINE": True,
}


def activate(database, values, candidate="CAND_DEMO"):
    rules = SqliteRuleRepository(database)
    for index, (name, value) in enumerate(values.items()):
        at = NOW - timedelta(days=1) + timedelta(seconds=index)
        current = rules.current(candidate)
        change = request(name, value)
        change.candidate_id = candidate
        change.provenance.decided_at = at
        change.expected_version = current.version if current else None
        proposal = make_proposal(change, current, now=at)
        rules.save_proposal(proposal)
        current = rules.approve(
            RuleConfirmation(
                proposal_id=proposal.proposal_id,
                question_digest=proposal.question_digest,
                answer="Synthetic exact policy confirmation",
                actor_id="synthetic owner",
                confirmed_at=at,
            ),
            candidate_id=candidate,
        )
    return current


def sent(store):
    from jobagent.jobs.jd_snapshot import text_digest

    record = create(
        store, draft_greeting="Synthetic", draft_digest=text_digest("Synthetic"), draft_version="v1"
    )
    event = command(record)
    proof = PipelineVerifiedEvidence(
        reference=event.evidence_reference,
        kind="send_audit",
        observed_at=event.changed_at,
        source_at=NOW,
        sent_text="Synthetic",
        sent_at=NOW,
        send_reference="AUDIT_SYNTHETIC",
    )
    return store.transition(event, proof, now=event.changed_at)


def no_reply(pair):
    job, meta = pair
    return PipelineObservation(
        event_id="POLICY_CHECK",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
        observed_at=NOW + timedelta(hours=49),
        kind="no_reply",
        evidence_kind="conversation_message",
        evidence_reference="SYNTHETIC_LOADED_CONVERSATION",
    )


def business_rows(database):
    names = [
        "pipeline_jobs",
        "pipeline_meta",
        "pipeline_state_history",
        "pipeline_observations",
        "pipeline_requests",
        "pipeline_used_sends",
    ]
    with database.connect() as connection:
        return {
            name: [tuple(row) for row in connection.execute(f"SELECT * FROM {name}")]
            for name in names
        }


@pytest.mark.parametrize(
    "changes",
    [
        {"ABANDON_HOURS": 72},
        {"ABANDON_IMMEDIATE_REASONS": ["job_closed"]},
        {"RESUME_STAGE_IN_ABANDON_LINE": False},
    ],
)
def test_incompatible_policy_blocks_real_observation_without_business_mutation(tmp_path, changes):
    store = repo(tmp_path)
    pair = sent(store)
    snapshot = activate(store.database, STATE_POLICY | changes)
    before = business_rows(store.database)
    event = no_reply(pair)
    with pytest.raises(ContractValidationError) as failure:
        store.observe(event, now=event.observed_at)
    assert failure.value.details["status"] == "not_integrated"
    assert failure.value.details["rules_version"] == snapshot.version
    assert not failure.value.details["can_write"]
    assert business_rows(store.database) == before


def test_active_profile_missing_policy_cannot_fall_back_at_direct_write_boundary(tmp_path):
    store = repo(tmp_path)
    job, meta = create(store)
    activate(store.database, {"TOP_PER_QUERY": 3})
    before = business_rows(store.database)
    with store.database.connect() as connection, connection:
        with pytest.raises(ContractValidationError) as failure:
            store.write_job(connection, job, meta.model_copy(update={"version": 2}))
        assert connection.in_transaction
    assert failure.value.details["status"] == "not_integrated"
    assert {item["variable"] for item in failure.value.details["conflicts"]} == set(STATE_POLICY)
    assert business_rows(store.database) == before


def test_direct_history_append_and_new_contact_cannot_bypass_policy_guard(tmp_path):
    store = repo(tmp_path)
    job, _meta = create(store)
    original = store.history(job.pipeline_id, job.candidate_id)[0]
    activate(store.database, STATE_POLICY | {"ABANDON_HOURS": 72})
    before = business_rows(store.database)
    with store.database.connect() as connection, connection, pytest.raises(ContractValidationError):
        store.append_history(connection, original.model_copy(update={"history_id": "BYPASS"}))
    with pytest.raises(ContractValidationError):
        create(store, pipeline_id="PIPE_1111111111111111", job_id="boss-other")
    assert business_rows(store.database) == before


def test_direct_writer_cannot_escape_policy_by_changing_candidate_identity(tmp_path):
    store = repo(tmp_path)
    job, meta = create(store)
    activate(store.database, STATE_POLICY | {"ABANDON_HOURS": 72})
    before = business_rows(store.database)
    with store.database.connect() as connection, connection, pytest.raises(ContractValidationError):
        store.write_job(connection, job.model_copy(update={"candidate_id": "CAND_OTHER"}), meta)
    assert business_rows(store.database) == before


def test_complete_compatible_policy_keeps_existing_production_semantics(tmp_path):
    store = repo(tmp_path)
    pair = sent(store)
    activate(store.database, STATE_POLICY)
    event = no_reply(pair)
    result = store.observe(event, now=event.observed_at)
    assert result[0].pipeline_state == "abandoned"
    assert result[0].state_reason == "no_reply_2d"
    assert len(store.history(result[0].pipeline_id, result[0].candidate_id)) == 3


def test_create_verifies_policy_at_supplied_operation_time_not_later_wall_clock(tmp_path):
    from jobagent.storage.pipeline_service import PipelineService
    from tests.storage.test_job_intake_service import setup

    intake, current, _ = setup(tmp_path)
    activate(intake.database, STATE_POLICY)
    pipeline = PipelineService(intake.database)
    before = business_rows(intake.database)
    with pytest.raises(ContractValidationError) as failure:
        pipeline.create(
            {
                "event_id": "BEFORE_EFFECTIVE",
                "candidate_id": "CAND_DEMO",
                "normalized_job_id": current.job_id,
                "evidence_reference": "SYNTHETIC_ENTRY",
                "salary_minimum_k": 18,
            },
            now=NOW - timedelta(days=2),
        )
    assert any(item["reason"] == "future_version" for item in failure.value.details["conflicts"])
    assert business_rows(intake.database) == before


def test_other_candidates_policy_does_not_block_legacy_candidate_and_due_reports_conflict(tmp_path):
    store = repo(tmp_path)
    pair = sent(store)
    activate(store.database, STATE_POLICY | {"ABANDON_HOURS": 72}, candidate="CAND_OTHER")
    assert len(store.due("CAND_DEMO", now=NOW + timedelta(hours=49))) == 1
    activate(store.database, STATE_POLICY | {"ABANDON_HOURS": 72})
    with pytest.raises(ContractValidationError):
        store.due("CAND_DEMO", now=NOW + timedelta(hours=49))
    assert store.get(pair[0].pipeline_id, pair[0].candidate_id) == pair


def test_exact_old_event_replay_is_readonly_after_policy_changes(tmp_path):
    store = repo(tmp_path)
    pair = sent(store)
    event = no_reply(pair)
    result = store.observe(event, now=event.observed_at)
    activate(store.database, STATE_POLICY | {"ABANDON_HOURS": 72})
    before = business_rows(store.database)
    assert store.observe(event, now=event.observed_at) == result
    assert business_rows(store.database) == before


def test_direct_response_cache_writer_cannot_manufacture_success_during_policy_conflict(tmp_path):
    store = repo(tmp_path)
    pair = create(store)
    activate(store.database, STATE_POLICY | {"ABANDON_HOURS": 72})
    before = business_rows(store.database)
    with store.database.connect() as connection, connection, pytest.raises(ContractValidationError):
        store.remember(connection, "FORGED_REPLAY", "sha256:synthetic", pair)
    assert business_rows(store.database) == before


@pytest.mark.parametrize("values", [{"RATIO_TRIGGER_FACTOR": 0.7}, {"TOP_PER_QUERY": 3}])
def test_factor_conflict_or_missing_blocks_diagnosis_but_not_factual_counts(tmp_path, values):
    from tests.storage.test_pipeline_metrics import compute_input, prepared, service

    pipeline, pair = prepared(tmp_path)
    metrics = service(pipeline.database)
    activate(pipeline.database, values)
    counts = metrics.compute(compute_input(pair), now=NOW + timedelta(days=1))
    request_data = {
        "candidate_id": "CAND_DEMO",
        "current_metric_ids": [item["metric_id"] for item in counts["metrics"]],
    }
    with pytest.raises(ContractValidationError) as failure:
        metrics.diagnose(request_data, now=NOW + timedelta(days=1))
    assert failure.value.details["status"] == "not_integrated"
    with pipeline.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_diagnoses").fetchone()[0] == 0
        reports = connection.execute("SELECT COUNT(*) FROM pipeline_diagnosis_reports").fetchone()[
            0
        ]
        assert reports == 0


def test_factor_guard_also_protects_rule_artifact_writes(tmp_path, monkeypatch):
    from tests.storage.test_pipeline_rules import proposal, seed

    rules, diagnosis = seed(tmp_path, monkeypatch)
    activate(rules.database, {"RATIO_TRIGGER_FACTOR": 0.7})
    with pytest.raises(ContractValidationError) as failure:
        rules.propose(proposal(diagnosis), now=NOW + timedelta(days=1))
    assert failure.value.details["status"] == "not_integrated"
    assert rules.confirmed("CAND_DEMO") == []
    with rules.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM message_rule_proposals").fetchone()[0] == 0


def test_low_level_rule_proposal_cannot_escape_original_diagnosis_candidate(tmp_path, monkeypatch):
    from tests.storage.test_pipeline_rules import seed

    rules, diagnosis = seed(tmp_path, monkeypatch)
    activate(rules.database, {"RATIO_TRIGGER_FACTOR": 0.7})
    with rules.database.connect() as connection, connection, pytest.raises(ContractValidationError):
        rules.save_proposal(
            connection,
            proposal_id="ESCAPE",
            candidate_id="CAND_OTHER",
            diagnosis=diagnosis.model_copy(update={"candidate_id": "CAND_OTHER"}),
            category="style",
            before=None,
            after="Synthetic rule",
            previous_id=None,
            operation="activate",
            input_digest="sha256:synthetic",
            now=NOW,
        )


def test_low_level_rule_decision_cannot_escape_saved_proposal_candidate(tmp_path, monkeypatch):
    from tests.storage.test_pipeline_rules import proposal, seed

    rules, diagnosis = seed(tmp_path, monkeypatch)
    original = rules.propose(proposal(diagnosis), now=NOW)
    activate(rules.database, {"RATIO_TRIGGER_FACTOR": 0.7})
    with rules.database.connect() as connection, connection, pytest.raises(ContractValidationError):
        rules.decision(
            connection,
            "ESCAPE",
            "CAND_OTHER",
            {**original, "candidate_id": "CAND_OTHER"},
            accepted=False,
            digest="sha256:synthetic",
            owner_text="Synthetic owner refusal",
            owner_reference="SYNTHETIC_MESSAGE",
            now=NOW,
        )


def test_generic_message_rule_route_cannot_withdraw_pipeline_diagnosis_rule(tmp_path, monkeypatch):
    from jobagent.storage.message_diff_repository import MessageDiffRepository
    from tests.storage.test_pipeline_rules import confirm, proposal, seed

    rules, diagnosis = seed(tmp_path, monkeypatch)
    original = rules.propose(proposal(diagnosis), now=NOW)
    activate(rules.database, {"RATIO_TRIGGER_FACTOR": 0.7})
    with pytest.raises(ContractValidationError):
        MessageDiffRepository(rules.database).confirm(confirm(original, accepted=False), now=NOW)
    with rules.database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM message_rule_confirmations").fetchone()[0] == 0
        )
