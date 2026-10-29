import json
from decimal import Decimal

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.pipeline_metrics import PipelineDiagnosis, PipelineExclusionCounts
from jobagent.storage.database import Database
from tests.jobs.test_pipeline_metric_contracts import END, START, scope


def save_diag(database, diag):
    values = diag.model_dump(mode="json", exclude={"schema_version"})
    for key in ("excluded_counts", "evidence_references"):
        values[key] = json.dumps(values[key])
    with database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO pipeline_diagnoses ("
            + ",".join(values)
            + ") VALUES ("
            + ",".join("?" for _ in values)
            + ")",
            tuple(values.values()),
        )


def seed(tmp_path, monkeypatch):
    from jobagent.storage.pipeline_rules import PipelineRuleService

    database = Database(tmp_path / "private.sqlite3")
    database.migrate()
    diag = PipelineDiagnosis(
        diagnosis_id="DIAG_SYNTHETIC",
        candidate_id="CAND_DEMO",
        metric_id="METRIC_SYNTHETIC",
        window_start=START,
        window_end=END,
        **scope(),
        stage_from="greeting_read",
        stage_to="initial_contact",
        historical_rate=Decimal("1"),
        sliced_cumulative_rate=Decimal("0"),
        optimized_rate=None,
        numerator=0,
        denominator=1,
        excluded_counts=PipelineExclusionCounts(
            **{k: 0 for k in PipelineExclusionCounts.model_fields if k != "schema_version"}
        ),
        diagnosis_code="greeting_issue",
        evidence_references=["PRIVATE_METRIC_LOG"],
        source_digest="sha256:current-evidence",
        rule_id=None,
        pre_rule_cumulative_rate=None,
    )
    save_diag(database, diag)
    service = PipelineRuleService(database)
    # Freshness and cumulative calculations have separate database integration tests.
    monkeypatch.setattr(service, "require_current_evidence", lambda *_args, **_kwargs: None)
    return service, diag


def proposal(diag, **changes):
    payload = dict(
        proposal_id="PRULE_SYNTHETIC",
        candidate_id="CAND_DEMO",
        diagnosis_id=diag.diagnosis_id,
        diagnosis_digest=diag.source_digest,
        category="style",
        rule_text_after="Use direct sentences.",
    )
    payload.update(changes)
    return payload


def confirm(p, **changes):
    payload = dict(
        confirmation_id="CONFIRM_SYNTHETIC",
        proposal_id=p["proposal_id"],
        candidate_id="CAND_DEMO",
        rule_hash=p["rule_hash"],
        accepted=True,
        owner_text="I confirm this exact scoped rule.",
        owner_reference="PRIVATE_OWNER_REPLY",
    )
    payload.update(changes)
    return payload


def test_ratio_diagnosis_with_one_job_can_propose_but_not_activate_without_owner(
    tmp_path, monkeypatch
):
    service, diag = seed(tmp_path, monkeypatch)
    p = service.propose(proposal(diag), now=END)
    assert p["operation"] == "activate" and p["baseline_rate"] == "0"
    assert service.confirmed("CAND_DEMO") == []
    assert service.propose(proposal(diag), now=END) == p
    service.confirm(confirm(p), now=END)
    assert service.confirmed("CAND_DEMO")[0]["rule_text"] == "Use direct sentences."
    active = service.metric_rule(p["proposal_id"], "CAND_DEMO")
    assert active.pre_rule_cumulative_rate == 0 and active.effective_at == END
    assert service.confirmed("CAND_OTHER") == []


def test_exact_owner_hash_and_current_evidence_are_required(tmp_path, monkeypatch):
    service, diag = seed(tmp_path, monkeypatch)
    p = service.propose(proposal(diag), now=END)
    for changes in [
        dict(rule_hash="sha256:wrong"),
        dict(owner_text=" "),
        dict(candidate_id="CAND_OTHER"),
    ]:
        with pytest.raises(ContractValidationError):
            service.confirm(confirm(p, **changes), now=END)

    def stale(*_args, **_kwargs):
        raise ContractValidationError("Underlying metric evidence changed.")

    monkeypatch.setattr(service, "require_current_evidence", stale)
    with pytest.raises(ContractValidationError):
        service.confirm(confirm(p), now=END)
    assert service.confirmed("CAND_DEMO") == []


def test_rejected_rule_stays_inactive_and_decision_ids_are_immutable(tmp_path, monkeypatch):
    service, diag = seed(tmp_path, monkeypatch)
    p = service.propose(proposal(diag), now=END)
    rejected = confirm(p, accepted=False)
    result = service.confirm(rejected, now=END)
    assert service.confirm(rejected, now=END) == result
    assert service.confirmed("CAND_DEMO") == []
    with pytest.raises(ContractValidationError):
        service.confirm(confirm(p), now=END)


def test_ineffective_review_only_proposes_rollback_until_owner_confirms(tmp_path, monkeypatch):
    service, diag = seed(tmp_path, monkeypatch)
    p = service.propose(proposal(diag), now=END)
    service.confirm(confirm(p), now=END)
    bad = diag.model_copy(
        update={
            "diagnosis_id": "DIAG_INEFFECTIVE",
            "rule_id": p["proposal_id"],
            "diagnosis_code": "optimization_ineffective",
            "optimized_rate": Decimal("0"),
            "pre_rule_cumulative_rate": Decimal("0"),
        }
    )
    save_diag(service.database, bad)
    data = dict(
        review_id="REVIEW",
        candidate_id="CAND_DEMO",
        rule_id=p["proposal_id"],
        diagnosis_id=bad.diagnosis_id,
        diagnosis_digest=bad.source_digest,
    )
    result = service.review(data, now=END)
    assert service.review(data, now=END) == result
    assert len(service.confirmed("CAND_DEMO")) == 1
    rollback = result["rollback_proposal"]
    assert rollback["operation"] == "withdraw"
    service.confirm(confirm(rollback, confirmation_id="OWNER_ROLLBACK"), now=END)
    assert service.confirmed("CAND_DEMO") == []


def test_ineffective_replacement_restores_exact_previous_rule_only_after_owner_decision(
    tmp_path, monkeypatch
):
    from datetime import timedelta

    service, diag = seed(tmp_path, monkeypatch)
    first = service.propose(proposal(diag), now=END)
    service.confirm(confirm(first), now=END)
    second = service.propose(
        proposal(
            diag,
            proposal_id="PRULE_REPLACEMENT",
            previous_proposal_id=first["proposal_id"],
            rule_text_before=first["rule_text"],
            rule_text_after="Use a different specific structure.",
        ),
        now=END + timedelta(seconds=1),
    )
    service.confirm(
        confirm(second, confirmation_id="CONFIRM_REPLACEMENT"), now=END + timedelta(seconds=1)
    )
    assert [p["proposal_id"] for p in service.confirmed("CAND_DEMO")] == [second["proposal_id"]]
    bad = diag.model_copy(
        update={
            "diagnosis_id": "DIAG_REPLACE_BAD",
            "rule_id": second["proposal_id"],
            "diagnosis_code": "optimization_ineffective",
            "optimized_rate": Decimal("0"),
            "pre_rule_cumulative_rate": Decimal("0"),
        }
    )
    save_diag(service.database, bad)
    report = service.review(
        dict(
            review_id="REVIEW_REPLACEMENT",
            candidate_id="CAND_DEMO",
            rule_id=second["proposal_id"],
            diagnosis_id=bad.diagnosis_id,
            diagnosis_digest=bad.source_digest,
        ),
        now=END + timedelta(seconds=2),
    )
    rollback = report["rollback_proposal"]
    assert rollback["operation"] == "restore" and rollback["rule_text_after"] == first["rule_text"]
    assert service.confirmed("CAND_DEMO")[0]["proposal_id"] == second["proposal_id"]
    service.confirm(
        confirm(rollback, confirmation_id="CONFIRM_RESTORE"), now=END + timedelta(seconds=3)
    )
    restored = service.confirmed("CAND_DEMO")
    assert len(restored) == 1 and restored[0]["proposal_id"] == first["proposal_id"]
    assert service.metric_rule(first["proposal_id"], "CAND_DEMO").effective_at == END + timedelta(
        seconds=3
    )


def test_rule_confirmation_records_are_append_only(tmp_path, monkeypatch):
    import sqlite3

    service, diag = seed(tmp_path, monkeypatch)
    p = service.propose(proposal(diag), now=END)
    service.confirm(confirm(p), now=END)
    with service.database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM message_rule_confirmations")
