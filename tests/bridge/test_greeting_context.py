import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.bridge.greeting_context import load_greeting_request
from jobagent.errors import ContractValidationError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.outreach.service import OutreachService
from jobagent.schemas.candidate import CandidateProfile, EvidenceItem
from jobagent.schemas.greeting import GreetingCorrection, GreetingSettings
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.outreach import OutreachDraft
from jobagent.schemas.sourcing_feedback import PagedCardState, SourcingFeedback
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def populated(tmp_path: Path, *, owner="CAND_TEST", source="manual", url=None,
              approved=True, person=False, warnings=None):
    path = tmp_path / "jobagent.sqlite3"
    db = Database(path)
    db.migrate()
    candidate = SqliteCandidateRepository(db)
    candidate.save_profile(CandidateProfile(id="CAND_TEST", full_name="Alex"))
    candidate.save_profile(CandidateProfile(id="CAND_OTHER", full_name="Other"))
    for cid, eid, text in [("CAND_TEST", "EVID_CURRENT", "Built research agents."),
                           ("CAND_TEST", "EVID_OLD", "Earlier claim."),
                           ("CAND_OTHER", "EVID_FOREIGN", "Built unrelated tools.")]:
        candidate.upsert_evidence(cid, EvidenceItem.model_validate({
            "id": eid, "type": "project", "statement": text,
            "confidence": "explicit", "user_confirmed": True,
            "source": {"type": "interview", "reference": "CHAT_FIXTURE"},
        }))
    job = JobNormalizer().normalize(SourceJobRecord(
        source=source, source_job_id="fixture-role", company="Fixture Labs",
        title="Research Agent Product", location="Shanghai",
        jd_raw="Build research products and evaluate grounded model answers.",
        url=url or "https://careers.fixture-company.org/role", collected_at=NOW,
    ))
    if warnings:
        job.warnings = warnings
    SqliteJobRepository(db).save_job(job)
    service = OutreachService()
    report = service.build_batch([
        OutreachDraft(job_id=job.id, platform=source,
                      text="Hello, I built research agents. Can we talk?",
                      evidence_ids=["EVID_CURRENT" if owner == "CAND_TEST" else "EVID_FOREIGN"],
                      written_by="person" if person else "agent"),
    ], jobs={job.id: job}, already_contacted=set(),
       confirmed_evidence_ids={"EVID_CURRENT", "EVID_FOREIGN"},
       batch_id="OBATCH_FIXTURE", created_at=NOW)
    batch = report.batch
    assert batch is not None
    store = SqliteOutreachRepository(db)
    store.save_batch(batch)
    ask = service.ask(batch, asked_at=NOW)
    store.save_ask(ask)
    if approved:
        approval = service.approve(batch, ask=ask, numbers=[1],
                                   attestation="Contact this role", approved_at=NOW)
        store.save_approval(approval)
    return path, job.id


def settings(**kwargs):
    return GreetingSettings(candidate_id="CAND_TEST", display_name="Alex", **kwargs)


def test_default_reads_only_owner_choices_and_leaves_database_unchanged(tmp_path):
    path, job_id = populated(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = load_greeting_request(path, settings())
    assert result.mode == "default" and result.job is None
    assert [x.job.job_id for x in result.interests] == [job_id]
    assert {x.id for x in result.evidence} == {"EVID_CURRENT", "EVID_OLD"}
    assert result.feedback == []
    assert "recruiter" not in result.interests[0].job.model_dump()
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("kwargs", [
    {"owner": "CAND_OTHER"}, {"approved": False}, {"source": "mock-alpha"},
    {"url": "https://jobs.example.test/role"}, {"source": "demo"},
])
def test_other_candidates_unapproved_and_synthetic_jobs_are_not_interest(tmp_path, kwargs):
    path, _ = populated(tmp_path, **kwargs)
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, settings())


def test_targeted_requires_full_stored_jd_but_does_not_need_previous_approval(tmp_path):
    path, job_id = populated(tmp_path, approved=False)
    result = load_greeting_request(path, settings(), job_id=job_id,
                                   feedback="Use clear product language")
    assert result.job.job_id == job_id and result.mode == "targeted"
    assert result.feedback == ["Use clear product language"]


@pytest.mark.parametrize("warning", ["JD_MISSING", "JD_TRUNCATED", "LISTING_ONLY"])
def test_known_incomplete_jd_is_rejected(tmp_path, warning):
    path, job_id = populated(tmp_path, warnings=[warning])
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, settings(), job_id=job_id)


def test_stale_approval_digest_and_unbound_ask_do_not_become_preferences(tmp_path):
    path, _ = populated(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE outreach_approvals SET approval_json = "
                     "json_set(approval_json, '$.batch_digest', 'sha256:stale')")
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, settings())


def test_unconfirmed_references_do_not_prove_candidate_interest(tmp_path):
    path, _ = populated(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE evidence_items SET evidence_json = "
                     "json_set(evidence_json, '$.user_confirmed', json('false')) "
                     "WHERE evidence_id = 'EVID_CURRENT'")
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, settings())


def test_explicit_selection_is_supported_but_scoped_settings_need_existing_candidate(tmp_path):
    path, job_id = populated(tmp_path, approved=False)
    result = load_greeting_request(path, settings(selected_job_ids=[job_id]))
    assert result.interests[0].selection_id == "owner_selection:" + job_id
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, GreetingSettings(candidate_id="CAND_MISSING",
                                                    display_name="Unknown"), job_id=job_id)


def test_corrections_need_exact_confirmed_same_candidate_provenance(tmp_path):
    path, _ = populated(tmp_path)
    correction = GreetingCorrection(older_id="EVID_OLD", replacement_id="EVID_CURRENT",
                                    replacement_excerpt="Built research agents.")
    result = load_greeting_request(path, settings(corrections=[correction]))
    assert [e.id for e in result.evidence] == ["EVID_CURRENT"]
    correction.replacement_id = "EVID_FOREIGN"
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, settings(corrections=[correction]))


def test_only_person_rewrites_enter_feedback_not_template_sentences(tmp_path):
    path, _ = populated(tmp_path, person=True)
    result = load_greeting_request(path, settings())
    assert len(result.feedback) == 1 and "I built research agents" in result.feedback[0]
    assert "OAPPROVAL_" in result.feedback[0]


@pytest.mark.parametrize("owner,demo,digest_ok,expected", [
    ("CAND_TEST", False, True, True), ("CAND_OTHER", False, True, False),
    ("CAND_TEST", True, True, False), ("CAND_TEST", False, False, False),
])
def test_card_feedback_needs_real_candidate_and_exact_text_binding(
    tmp_path, owner, demo, digest_ok, expected,
):
    path, job_id = populated(tmp_path)
    with sqlite3.connect(path) as conn:
        ask_id = conn.execute("SELECT ask_id FROM outreach_asks").fetchone()[0]
        words = "Hello, I built research agents. Can we talk?"
        state = PagedCardState(
            message_id="MESSAGE_FIXTURE", batch_id="OBATCH_FIXTURE", ask_id=ask_id,
            candidate_id=owner, expires_at=NOW, demo_mode=demo, decisions={"1": "declined"},
        )
        event = SourcingFeedback(
            event_id="EVENT_FIXTURE", job_id=job_id, source="manual",
            query_strategy_version="VERSION_FIXTURE", action="decline", reason_category="copy",
            free_text="Use a more direct product example.", actor_id="OWNER_FIXTURE",
            content_digest="sha256:" + hashlib.sha256(words.encode()).hexdigest()
            if digest_ok else "sha256:unrelated", occurred_at=NOW,
            idempotency_key="EVENT_FIXTURE",
        )
        conn.execute("INSERT INTO paged_card_states VALUES (?, ?, ?)",
                     (state.message_id, 0, state.model_dump_json()))
        conn.execute("INSERT INTO paged_card_events VALUES (?, ?, ?)",
                     (event.event_id, state.message_id, NOW.isoformat()))
        conn.execute("INSERT INTO sourcing_feedback_events VALUES (?, ?, ?, ?, ?)",
                     (event.event_id, event.idempotency_key, event.source,
                      event.model_dump_json(), NOW.isoformat()))
    result = load_greeting_request(path, settings())
    assert bool(result.feedback) is expected
    if expected:
        assert "Use a more direct product example" in result.feedback[0]
        assert "OWNER_FIXTURE" not in result.feedback[0]


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ContractValidationError):
        load_greeting_request(path, settings())
    assert not path.exists()
