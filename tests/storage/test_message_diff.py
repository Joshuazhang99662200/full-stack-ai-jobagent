from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import text_digest
from tests.jobs.test_message_diff import sample
from tests.storage.test_job_intake import NOW
from tests.storage.test_job_intake_service import setup


def repository(tmp_path):
    from jobagent.storage.message_diff_repository import MessageDiffRepository

    service, _, _ = setup(tmp_path)
    for i in (2, 3):
        setup(tmp_path, number=i)
    return MessageDiffRepository(service.database)


def record(repo, payload):
    return repo.record(payload, now=NOW + timedelta(hours=1))


def test_single_sample_never_promotes_and_accept_does_not_mean_job_like(tmp_path):
    repo = repository(tmp_path)
    payload = sample(human_picked=True, job_preference=None, message_feedback="accepted")
    result = record(repo, payload)
    assert result == record(repo, payload)
    report = repo.report("CAND_DEMO")
    fact = report["categories"]["fact_correction"]
    assert fact["sample_count"] == 1 and fact["maturity"] == "observed_once"
    assert report["evaluation_candidates"] == [] and repo.confirmed_rules("CAND_DEMO") == []
    with pytest.raises(ContractValidationError):
        repo.propose(
            dict(
                proposal_id="RULE_1",
                candidate_id="CAND_DEMO",
                category="fact_correction",
                rule_text="Use only confirmed facts.",
                report_digest=report["report_digest"],
            ),
            now=NOW,
        )
    with repo.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM intake_signals").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM jd_feature_sets").fetchone()[0] == 0


def test_distinct_jobs_and_human_confirmation_are_both_required(tmp_path):
    repo = repository(tmp_path)
    record(repo, sample())
    # Different event IDs on the same job/episode supersede, never add independent jobs.
    record(repo, sample(event_id="DUPLICATE_SAMPLE", occurred_at=NOW + timedelta(seconds=1)))
    assert repo.report("CAND_DEMO")["categories"]["fact_correction"]["sample_count"] == 1
    record(repo, sample(2))
    assert repo.report("CAND_DEMO")["categories"]["fact_correction"]["maturity"] == "repeated"
    record(repo, sample(3))
    report = repo.report("CAND_DEMO")
    assert report["categories"]["fact_correction"]["maturity"] == "stable"
    assert report["evaluation_candidates"] == ["fact_correction"]
    assert repo.confirmed_rules("CAND_DEMO") == []
    proposal = repo.propose(
        dict(
            proposal_id="RULE_1",
            candidate_id="CAND_DEMO",
            category="fact_correction",
            rule_text="Use only confirmed facts.",
            report_digest=report["report_digest"],
        ),
        now=NOW,
    )
    confirmation = dict(
        confirmation_id="OWNER_1",
        proposal_id="RULE_1",
        candidate_id="CAND_DEMO",
        rule_hash=proposal["rule_hash"],
        accepted=True,
        owner_text="I confirm this exact rule.",
        owner_reference="PRIVATE_OWNER_REPLY",
    )
    with pytest.raises(ContractValidationError):
        repo.confirm({**confirmation, "rule_hash": text_digest("different")}, now=NOW)
    repo.confirm(confirmation, now=NOW)
    assert repo.confirmed_rules("CAND_DEMO")[0]["rule_text"] == "Use only confirmed facts."
    assert repo.confirmed_rules("CAND_OTHER") == []
    repo.confirm(
        {**confirmation, "confirmation_id": "OWNER_2", "accepted": False},
        now=NOW + timedelta(seconds=1),
    )
    assert repo.confirmed_rules("CAND_DEMO") == []


def test_restoring_original_card_text_removes_false_signal_and_stales_old_report(tmp_path):
    repo = repository(tmp_path)
    for i in (1, 2, 3):
        record(repo, sample(i))
    before = repo.report("CAND_DEMO")
    reverted = sample(
        event_id="RESTORED",
        occurred_at=NOW + timedelta(minutes=1),
        final_text="Initial claim.",
        final_hash=text_digest("Initial claim."),
        labels=[],
    )
    assert not record(repo, reverted)["changed"]
    after = repo.report("CAND_DEMO")
    assert after["categories"]["fact_correction"]["sample_count"] == 2
    assert after["evaluation_candidates"] == []
    with pytest.raises(ContractValidationError):
        repo.propose(
            dict(
                proposal_id="STALE",
                candidate_id="CAND_DEMO",
                category="fact_correction",
                rule_text="Do not infer.",
                report_digest=before["report_digest"],
            ),
            now=NOW,
        )


def test_private_diff_events_are_immutable_and_candidate_scoped(tmp_path):
    repo = repository(tmp_path)
    record(repo, sample())
    with pytest.raises(ContractValidationError):
        record(repo, sample(final_text="Changed", final_hash=text_digest("Changed"), labels=[]))
    assert repo.report("CAND_OTHER")["total_changed_samples"] == 0
    with pytest.raises(ContractValidationError):
        record(repo, sample(99))


def test_multiple_internal_ids_for_same_platform_job_do_not_inflate_maturity(tmp_path):
    from jobagent.storage.job_repository import SqliteJobRepository

    repo = repository(tmp_path)
    jobs = SqliteJobRepository(repo.database)
    original = jobs.get_job("JOB_DEMO_1")
    for i in (2, 3):
        jobs.save_job(original.model_copy(update={"id": f"JOB_DEMO_{i}"}))
    for i in (1, 2, 3):
        record(repo, sample(i))
    fact = repo.report("CAND_DEMO")["categories"]["fact_correction"]
    assert fact["sample_count"] == 1 and fact["maturity"] == "observed_once"


def test_rule_confirmation_rejects_changed_evidence_after_proposal(tmp_path):
    repo = repository(tmp_path)
    for i in (1, 2, 3):
        record(repo, sample(i))
    report = repo.report("CAND_DEMO")
    proposal = repo.propose(
        dict(
            proposal_id="BEFORE_REVERT",
            candidate_id="CAND_DEMO",
            category="fact_correction",
            rule_text="Confirm facts.",
            report_digest=report["report_digest"],
        ),
        now=NOW,
    )
    record(
        repo,
        sample(
            event_id="LATER_RESTORE",
            occurred_at=NOW + timedelta(minutes=1),
            final_text="Initial claim.",
            final_hash=text_digest("Initial claim."),
            labels=[],
        ),
    )
    with pytest.raises(ContractValidationError):
        repo.confirm(
            dict(
                confirmation_id="TOO_LATE",
                proposal_id="BEFORE_REVERT",
                candidate_id="CAND_DEMO",
                rule_hash=proposal["rule_hash"],
                accepted=True,
                owner_text="I approve.",
                owner_reference="OWNER_REPLY",
            ),
            now=NOW,
        )
    assert repo.confirmed_rules("CAND_DEMO") == []
