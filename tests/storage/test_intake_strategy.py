from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_job_intake import NOW
from tests.storage.test_job_intake_service import command, policy, setup


def add(tmp_path, number, **changes):
    service, row, snapshot = setup(tmp_path, number=number, **changes)
    row = service.attach_snapshot(command(row, snapshot_id=snapshot.snapshot_id), now=NOW)
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    return service, row


def strategy(service):
    from jobagent.storage.intake_strategy import IntakeStrategyService

    return IntakeStrategyService(service.database)


def data(**changes):
    return dict(
        candidate_id="CAND_DEMO",
        domain="design",
        source="boss",
        baseline_queries=["设计师"],
        **changes,
    )


def start_run(service, run_id="RUN_NEXT"):
    from jobagent.schemas.sourcing import SourcingRunRequest
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    meter = SqliteSourcingRepository(service.database)
    meter.start_run(
        SourcingRunRequest(run_id=run_id, source="boss", candidate_id="CAND_DEMO"),
        now=NOW,
        daily_cap=50,
    )
    return meter


def test_complete_manual_flow_builds_next_round_from_all_prior_samples(tmp_path):
    service, first = add(tmp_path, 1)
    engine = strategy(service)
    initial = engine.rebuild(data(), policy(), now=NOW)
    assert initial["plan"]["status"] == "needs_seed"
    service, _second = add(tmp_path, 2)
    updated = engine.rebuild(data(), policy(), now=NOW + timedelta(seconds=1))
    assert updated["plan"]["ordered_queries"]
    assert updated["lexicon"]["based_on_snapshots"] == 2
    assert all(term["count"] == 2 for term in updated["lexicon"]["terms"])
    assert updated["input"]["request"]["learning"]["signals"]
    again = engine.rebuild(data(), policy(), now=NOW + timedelta(seconds=1))
    assert again["plan"]["version"] == updated["plan"]["version"]
    assert (
        engine.active("CAND_DEMO", "design", "boss")["version_digest"] == updated["version_digest"]
    )
    current = service.repository.get(first.intake_id, first.candidate_id)
    assert current.plan_id == updated["plan"]["version"]
    service, _third = add(tmp_path, 3)
    stable = engine.rebuild(data(), policy(), now=NOW + timedelta(seconds=2))
    assert all(t["maturity"] == "stable" for t in stable["lexicon"]["terms"])


def test_reference_only_or_message_acceptance_does_not_become_owner_like(tmp_path):
    service, _ = add(tmp_path, 1, job_preference=None, owner_text="")
    engine = strategy(service)
    result = engine.rebuild(data(), policy(), now=NOW)
    assert result["input"]["request"]["learning"]["signals"] == []
    assert all(term["preference_weight"] == 0 for term in result["lexicon"]["terms"])


def test_active_policy_keeps_manual_versions_and_detects_stale_source(tmp_path):
    service, _ = add(tmp_path, 1)
    engine = strategy(service)
    first = engine.rebuild(data(), policy(), now=NOW)
    # Rebuilding from the active derived MD preserves absolute version semantics.
    from jobagent.schemas.lexicon import Lexicon

    again = engine.rebuild(data(), Lexicon.model_validate(first["lexicon"]), now=NOW)
    assert again["version_digest"] == first["version_digest"]
    service, _ = add(tmp_path, 2)
    with pytest.raises(ContractValidationError):
        engine.active("CAND_DEMO", "design", "boss", require_current=True)
    with pytest.raises(ContractValidationError):
        engine.active("CAND_OTHER", "design", "boss")


def test_plan_claim_is_bound_to_real_candidate_source_and_frozen_for_round(tmp_path):
    service, _ = add(tmp_path, 1)
    service, _ = add(tmp_path, 2)
    engine = strategy(service)
    result = engine.rebuild(data(), policy(), now=NOW)
    start_run(service)
    claim = dict(candidate_id="CAND_DEMO", domain="design", run_id="RUN_NEXT")
    bound = engine.claim(claim, now=NOW)
    assert bound["plan"]["version"] == result["plan"]["version"]
    assert engine.claim(claim, now=NOW) == bound
    service, _ = add(tmp_path, 3)
    engine.rebuild(data(), policy(), now=NOW + timedelta(seconds=1))
    assert engine.claim(claim, now=NOW + timedelta(seconds=1)) == bound
    with pytest.raises(ContractValidationError):
        engine.claim({**claim, "candidate_id": "CAND_OTHER"}, now=NOW)
    with service.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM intake_search_executions").fetchone()[0] == 0


def test_only_actual_successful_budget_query_can_be_recorded_as_execution(tmp_path):
    service, _ = add(tmp_path, 1)
    service, _ = add(tmp_path, 2)
    engine = strategy(service)
    engine.rebuild(data(), policy(), now=NOW)
    meter = start_run(service)
    claim = dict(candidate_id="CAND_DEMO", domain="design", run_id="RUN_NEXT")
    bound = engine.claim(claim, now=NOW)
    query = bound["plan"]["ordered_queries"][0]["query"]
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest

    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_QUERY", run_id="RUN_NEXT", kind="query", search_term=query
        ),
        now=NOW,
    )
    with pytest.raises(ContractValidationError):
        engine.record_search({**claim, "attempt_id": "ATT_QUERY", "new_count": 0}, now=NOW)
    meter.complete(
        SourcingResultRequest(attempt_id="ATT_QUERY", outcome="complete", listing_count=7),
        now=NOW + timedelta(seconds=1),
    )
    recorded = engine.record_search(
        {**claim, "attempt_id": "ATT_QUERY", "new_count": 0}, now=NOW + timedelta(seconds=1)
    )
    assert recorded["query"] == query and recorded["plan_id"] == bound["plan"]["version"]
    assert (
        engine.record_search(
            {**claim, "attempt_id": "ATT_QUERY", "new_count": 0}, now=NOW + timedelta(seconds=1)
        )
        == recorded
    )
    with service.database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM intake_search_executions").fetchone()[0] == 1
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_UNPLANNED", run_id="RUN_NEXT", kind="query", search_term="unplanned"
        ),
        now=NOW,
    )
    meter.complete(
        SourcingResultRequest(attempt_id="ATT_UNPLANNED", outcome="complete", listing_count=1),
        now=NOW,
    )
    with pytest.raises(ContractValidationError):
        engine.record_search({**claim, "attempt_id": "ATT_UNPLANNED", "new_count": 0}, now=NOW)


def test_crash_before_activation_leaves_old_active_version_intact(tmp_path, monkeypatch):
    service, _ = add(tmp_path, 1)
    engine = strategy(service)
    old = engine.rebuild(data(), policy(), now=NOW)
    service, _ = add(tmp_path, 2)

    def fail(*args, **kwargs):
        raise ContractValidationError("synthetic activation failure")

    monkeypatch.setattr(engine, "activate", fail)
    with pytest.raises(ContractValidationError):
        engine.rebuild(data(), policy(), now=NOW)
    assert engine.active("CAND_DEMO", "design", "boss")["plan"]["version"] == old["plan"]["version"]


def test_latest_interest_withdrawal_removes_bonus_not_objective_count(tmp_path):
    service, first = add(tmp_path, 1)
    service, _ = add(tmp_path, 2)
    engine = strategy(service)
    before = engine.rebuild(data(), policy(), now=NOW)
    assert any(t["preference_weight"] > 0 for t in before["lexicon"]["terms"])
    first = service.repository.get(first.intake_id, first.candidate_id)
    service.set_interest(
        command(
            first,
            job_preference="neutral",
            owner_text="撤回方向偏好",
            message_reference="OWNER_NEUTRAL",
        ),
        now=NOW + timedelta(seconds=1),
    )
    after = engine.rebuild(data(), policy(), now=NOW + timedelta(seconds=2))
    assert all(t["count"] == 2 and t["preference_weight"] == 0 for t in after["lexicon"]["terms"])


def test_record_rotates_queries_once_and_never_records_unexecuted_plans(
    tmp_path,
):
    service, _ = add(tmp_path, 1)
    service, _ = add(tmp_path, 2)
    engine = strategy(service)
    engine.rebuild(data(), policy(), now=NOW)
    assert service.jobs.searches() == []
    meter = start_run(service)
    claim = dict(candidate_id="CAND_DEMO", domain="design", run_id="RUN_NEXT")
    bound = engine.claim(claim, now=NOW)
    query = bound["plan"]["ordered_queries"][0]["query"]
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest

    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_ROTATE", run_id="RUN_NEXT", kind="query", search_term=query
        ),
        now=NOW,
    )
    meter.complete(
        SourcingResultRequest(attempt_id="ATT_ROTATE", outcome="complete", listing_count=7), now=NOW
    )
    engine.record_search({**claim, "attempt_id": "ATT_ROTATE", "new_count": 0}, now=NOW)
    engine.record_search({**claim, "attempt_id": "ATT_ROTATE", "new_count": 0}, now=NOW)
    history = service.jobs.searches()
    assert len(history) == 1 and history[0].search_term == query
    plan = engine.rebuild(data(), policy(), now=NOW + timedelta(seconds=1))["plan"]
    assert query not in [q["query"] for q in plan["ordered_queries"]]


def test_next_round_cannot_reuse_active_plan_after_search_history_changes(tmp_path):
    service, _ = add(tmp_path, 1)
    service, _ = add(tmp_path, 2)
    engine = strategy(service)
    engine.rebuild(data(), policy(), now=NOW)
    meter = start_run(service)
    claim = dict(candidate_id="CAND_DEMO", domain="design", run_id="RUN_NEXT")
    bound = engine.claim(claim, now=NOW)
    query = bound["plan"]["ordered_queries"][0]["query"]
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest

    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_STALE", run_id="RUN_NEXT", kind="query", search_term=query
        ),
        now=NOW,
    )
    meter.complete(
        SourcingResultRequest(attempt_id="ATT_STALE", outcome="complete", listing_count=0), now=NOW
    )
    engine.record_search({**claim, "attempt_id": "ATT_STALE", "new_count": 0}, now=NOW)
    start_run(service, run_id="RUN_AFTER")
    with pytest.raises(ContractValidationError):
        engine.claim({**claim, "run_id": "RUN_AFTER"}, now=NOW)


def test_new_model_candidate_does_not_cause_version_growth_on_unchanged_replay(tmp_path):
    service, row = add(tmp_path, 1)
    from jobagent.jobs.jd_features import span_attributes
    from jobagent.schemas.lexicon import JDFeature

    feature_set = service.features(row.feature_set_id)
    snapshot = service.knowledge.get(row.snapshot_id)
    start = snapshot.jd_text.index("用户研究")
    proposal = feature_set.model_copy(
        update={
            "features": [
                *feature_set.features,
                JDFeature(
                    dimension="scenario",
                    term="用户研究",
                    evidence="用户研究",
                    start=start,
                    end=start + 4,
                    **span_attributes(snapshot.jd_text, start, start + 4),
                ),
            ]
        }
    )
    service.factorize(command(row), policy(), proposal=proposal.model_dump(mode="json"), now=NOW)
    engine = strategy(service)
    first = engine.rebuild(data(), policy(), now=NOW)
    assert any(t["term"] == "用户研究" for t in first["lexicon"]["terms"])
    again = engine.rebuild(data(), policy(), now=NOW)
    assert again["version_digest"] == first["version_digest"]


def test_upgrade_keeps_preexisting_domain_snapshots_and_owner_feedback(tmp_path):
    service, _ = add(tmp_path, 1)
    from jobagent.jobs.jd_features import extract_features
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.schemas.job_intelligence import SourceJobRecord
    from jobagent.schemas.search_learning import SearchLearningRequest, SearchSignal

    legacy = service.knowledge.capture(
        JDSnapshotInput(
            observation_id="LEGACY_OBS",
            job_id="JOB_LEGACY",
            job_url="https://example.com/legacy",
            platform="boss",
            fetched_at=NOW - timedelta(days=2),
            title="设计师",
            company="历史合成公司",
            jd_text="品牌设计师使用Figma。",
            completeness="full",
            discovery_kind="manual",
        )
    ).snapshot
    service.knowledge.save_features(extract_features(legacy, policy()), "sha256:legacy-policy")
    old_signal = SearchSignal(
        event_id="LEGACY_INTEREST",
        candidate_id="CAND_DEMO",
        kind="user_added",
        occurred_at=NOW - timedelta(days=1),
        owner_text="这个岗位是我喜欢的方向",
        features={"品牌": "品牌", "设计师": "设计师", "Figma": "Figma"},
        job=SourceJobRecord(
            source="boss",
            source_job_id="legacy",
            title=legacy.title,
            company=legacy.company,
            location="上海",
            jd_raw=legacy.jd_text,
            url=legacy.job_url,
            collected_at=legacy.fetched_at,
        ),
    )
    historical = SearchLearningRequest(
        candidate_id="CAND_DEMO", baseline_queries=["设计师"], signals=[old_signal]
    )
    imported_policy = policy().model_copy(update={"snapshot_ids": [legacy.snapshot_id]})
    engine = strategy(service)
    first = engine.rebuild(
        data(historical_learning=historical.model_dump()), imported_policy, now=NOW
    )
    assert first["lexicon"]["based_on_snapshots"] == 2
    assert all(t["count"] == 2 and t["preference_weight"] > 0 for t in first["lexicon"]["terms"])
    second = engine.rebuild(data(), policy(), now=NOW)
    assert second["lexicon"]["based_on_snapshots"] == 2
    assert second["version_digest"] == first["version_digest"]


def test_concurrent_policy_activation_cannot_overwrite_the_newer_active_version(
    tmp_path, monkeypatch
):
    service, _ = add(tmp_path, 1)
    engine = strategy(service)
    engine.rebuild(data(), policy(), now=NOW)
    original_activate = engine.activate
    newer = policy().model_copy(
        update={
            "terms": [t.model_copy(update={"weight": 2.0}) for t in policy().terms],
        }
    )

    def interleave(*args, **kwargs):
        strategy(service).rebuild(data(), newer, now=NOW)
        original_activate(*args, **kwargs)

    monkeypatch.setattr(engine, "activate", interleave)
    with pytest.raises(ContractValidationError):
        engine.rebuild(data(), policy(), now=NOW)
    assert all(
        t["weight"] == 2.0 for t in engine.active("CAND_DEMO", "design", "boss")["lexicon"]["terms"]
    )
