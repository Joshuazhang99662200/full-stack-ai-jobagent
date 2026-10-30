from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError
from jobagent.storage.database import Database
from tests.rules.test_dynamic_registry import request


def test_rule_activation_is_scoped_stale_safe_and_notice_survives_reads(tmp_path):
    from jobagent.rules.service import make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation
    from jobagent.storage.rule_repository import SqliteRuleRepository

    db = Database(tmp_path / "rules.sqlite3")
    db.migrate()
    repo = SqliteRuleRepository(db)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    one = make_proposal(request(), None, now=now)
    stale = make_proposal(request("PENDING_BACKLOG_ASK_THRESHOLD", 15), None, now=now)
    repo.save_proposal(one)
    repo.save_proposal(stale)
    confirmation = RuleConfirmation(
        proposal_id=one.proposal_id,
        question_digest=one.question_digest,
        answer="Synthetic exact approval",
        actor_id="synthetic owner",
        confirmed_at=now,
    )
    current = repo.approve(confirmation, candidate_id="CAND_SYNTHETIC")
    assert repo.current("CAND_OTHER") is None
    assert repo.current("CAND_SYNTHETIC").version == current.version
    assert len(repo.pending_notices("CAND_SYNTHETIC")) == 1
    assert len(repo.pending_notices("CAND_SYNTHETIC")) == 1
    with pytest.raises(ContractValidationError, match="stale"):
        repo.approve(
            confirmation.model_copy(
                update={
                    "proposal_id": stale.proposal_id,
                    "question_digest": stale.question_digest,
                }
            ),
            candidate_id="CAND_SYNTHETIC",
        )
    assert len(repo.history("CAND_SYNTHETIC")) == 1
    repo.acknowledge(
        "CAND_SYNTHETIC", current.version, reference="synthetic notification receipt", at=now
    )
    assert not repo.pending_notices("CAND_SYNTHETIC")


def test_proposal_not_saved_or_answer_before_question_cannot_activate(tmp_path):
    from jobagent.rules.service import make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation
    from jobagent.storage.rule_repository import SqliteRuleRepository

    db = Database(tmp_path / "rules.sqlite3")
    db.migrate()
    repo = SqliteRuleRepository(db)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    proposal = make_proposal(request(), None, now=now)
    decision = RuleConfirmation(
        proposal_id=proposal.proposal_id,
        question_digest=proposal.question_digest,
        answer="Synthetic approval",
        actor_id="synthetic owner",
        confirmed_at=now,
    )
    with pytest.raises(ContractValidationError, match="proposal"):
        repo.approve(decision, candidate_id="CAND_SYNTHETIC")


def test_active_parameters_cannot_silently_fall_back_or_load_stale_export(tmp_path):
    from datetime import timedelta

    from jobagent.bridge.dynamic_rules import load_effective_rule_snapshot
    from jobagent.rules.service import make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation
    from jobagent.storage.rule_repository import SqliteRuleRepository

    private = tmp_path / ".jobagent"
    private.mkdir()
    db = Database(private / "rules.sqlite3")
    db.migrate()
    repo = SqliteRuleRepository(db)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    one = make_proposal(request("DETAIL_CAP_PER_DAY", 2), None, now=at)
    repo.save_proposal(one)
    first = repo.approve(
        RuleConfirmation(
            proposal_id=one.proposal_id,
            question_digest=one.question_digest,
            answer="Synthetic approval",
            actor_id="synthetic owner",
            confirmed_at=at,
        ),
        candidate_id="CAND_SYNTHETIC",
    )
    path = private / "old.json"
    path.write_text(first.model_dump_json())
    with pytest.raises(ContractValidationError, match="explicit"):
        load_effective_rule_snapshot(None, "CAND_SYNTHETIC", db.path)
    change = request("DETAIL_CAP_PER_DAY", 3)
    change.expected_version = first.version
    change.provenance.decided_at = at + timedelta(seconds=1)
    second = make_proposal(change, first, now=at + timedelta(seconds=1))
    repo.save_proposal(second)
    repo.approve(
        RuleConfirmation(
            proposal_id=second.proposal_id,
            question_digest=second.question_digest,
            answer="Synthetic newer approval",
            actor_id="synthetic owner",
            confirmed_at=at + timedelta(seconds=1),
        ),
        candidate_id="CAND_SYNTHETIC",
    )
    with pytest.raises(ContractValidationError, match="stale"):
        load_effective_rule_snapshot(path, "CAND_SYNTHETIC", db.path)
