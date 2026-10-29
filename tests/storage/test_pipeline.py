import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.pipeline import PipelineMeta, PipelineTransition, PipelineVerifiedEvidence
from jobagent.storage.database import Database
from tests.jobs.test_pipeline_contracts import NOW, row


def repo(tmp_path):
    from jobagent.storage.pipeline_repository import PipelineRepository

    db = Database(tmp_path / "private.sqlite3")
    db.migrate()
    return PipelineRepository(db)


def create(store, **changes):
    job = row(**changes)
    meta = PipelineMeta(
        pipeline_id=job.pipeline_id,
        normalized_job_id="JOB_DEMO_1",
        entered_evidence_reference="ENTRY",
    )
    return store.create(job, meta, event_id="CREATE", evidence_reference="ENTRY")


def command(record, **changes):
    job, meta = record
    data = dict(
        event_id="SEND",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
        from_state=job.pipeline_state,
        to_state="greeting_sent",
        changed_at=NOW + timedelta(seconds=1),
        evidence_kind="send_audit",
        evidence_reference="AUDIT_SYNTHETIC",
        reason_code="normal",
    )
    data.update(changes)
    return PipelineTransition.model_validate(data)


def test_standard_form_exactly_matches_master_and_history_is_append_only(tmp_path):
    store = repo(tmp_path)
    job, meta = create(store)
    form = store.form(job.candidate_id)
    assert len(form) == 1
    assert form[0] == job.model_dump(mode="json", exclude={"schema_version"})
    history = store.history(job.pipeline_id, job.candidate_id)
    assert len(history) == 1 and history[0].from_state is None
    assert store.create(job, meta, event_id="CREATE", evidence_reference="ENTRY")[0] == job
    with store.database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM pipeline_state_history")
    with pytest.raises(ContractValidationError):
        store.get(job.pipeline_id, "CAND_OTHER")


def test_state_and_history_change_atomically_and_send_proof_is_single_use(tmp_path):
    from jobagent.jobs.jd_snapshot import text_digest

    store = repo(tmp_path)
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
    result = store.transition(event, proof, now=event.changed_at)
    assert result[0].pipeline_state == "greeting_sent" and result[1].proof_status == "verified"
    assert len(store.history(result[0].pipeline_id, result[0].candidate_id)) == 2
    assert store.transition(event, proof, now=event.changed_at) == result
    with pytest.raises(ContractValidationError):
        store.transition(
            event.model_copy(update={"evidence_reference": "OTHER"}), proof, now=event.changed_at
        )
    assert store.form(result[0].candidate_id)[0]["sent_greeting"] == "Synthetic"


def test_cas_allows_one_observation_and_rejected_mutations_are_audited(tmp_path):
    from jobagent.schemas.pipeline import PipelineObservation

    store = repo(tmp_path)
    job, meta = create(store)

    def pause(number):
        event = PipelineObservation(
            event_id=f"PAUSE_{number}",
            pipeline_id=job.pipeline_id,
            candidate_id=job.candidate_id,
            expected_version=meta.version,
            observed_at=NOW,
            kind="pause",
            evidence_kind="platform_state",
            evidence_reference="LOGIN_SCREEN",
        )
        try:
            store.observe(event, now=NOW)
            return True
        except ContractValidationError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(pause, [1, 2])) == 1
    with store.database.connect() as connection:
        rejected = connection.execute("SELECT COUNT(*) FROM pipeline_rejections").fetchone()[0]
        assert rejected == 1
    assert len(store.history(job.pipeline_id, job.candidate_id)) == 1
    assert store.get(job.pipeline_id, job.candidate_id)[1].paused


def test_same_job_active_row_is_unique_and_recontact_requires_owner_choice(tmp_path):
    store = repo(tmp_path)
    job, meta = create(store)
    with pytest.raises(ContractValidationError):
        store.create(
            job.model_copy(update={"pipeline_id": "PIPE_1111111111111111"}),
            meta.model_copy(update={"pipeline_id": "PIPE_1111111111111111"}),
            event_id="DUPLICATE",
            evidence_reference="SECOND_ENTRY",
        )


def test_new_tables_keep_private_payloads_out_of_rejection_log(tmp_path):
    store = repo(tmp_path)
    job, _meta = create(store)
    invalid = dict(
        event_id="BAD",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=1,
        from_state="draft_pending",
        to_state="interviewed",
        changed_at=NOW,
        evidence_kind="owner_message",
        evidence_reference="REF",
        owner_text="PRIVATE_SENTINEL",
        reason_code="normal",
    )
    with pytest.raises(ContractValidationError):
        store.reject_invalid(invalid, now=NOW)
    with store.database.connect() as connection:
        rows = connection.execute("SELECT * FROM pipeline_rejections").fetchall()
    assert rows and "PRIVATE_SENTINEL" not in json.dumps([dict(r) for r in rows])
