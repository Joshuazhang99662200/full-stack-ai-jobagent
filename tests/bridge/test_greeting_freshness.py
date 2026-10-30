import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.bridge.greeting_freshness import verify_greeting_sources
from jobagent.errors import StaleApprovalError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.outreach.generation import content_digest
from jobagent.schemas.candidate import CandidateProfile, Confidence, EvidenceItem
from jobagent.schemas.greeting import GreetingJob
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.outreach import OutreachDraft, OutreachItem, OutreachSourceBinding
from jobagent.skill_resources import read_reference
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


@pytest.fixture
def sources(tmp_path: Path):
    db = Database(tmp_path / "freshness.sqlite3")
    db.migrate()
    candidates = SqliteCandidateRepository(db)
    candidates.save_profile(CandidateProfile(id="CAND_TEST", full_name="Synthetic Alex"))
    candidates.save_profile(CandidateProfile(id="CAND_OTHER", full_name="Synthetic Other"))
    evidence = []
    # Deliberately different from repository ordering: the snapshot binds its own order.
    for eid in ["EVID_B", "EVID_A"]:
        item = EvidenceItem.model_validate({
            "id": eid, "type": "project", "statement": "Built synthetic research agents.",
            "confidence": "explicit", "user_confirmed": True,
            "source": {"type": "interview", "reference": "CHAT_SYNTHETIC"},
        })
        candidates.upsert_evidence("CAND_TEST", item)
        evidence.append(item)
    job = JobNormalizer().normalize(SourceJobRecord(
        source="manual", source_job_id="synthetic-role", company="Synthetic Labs",
        title="Research Agent Product", location="Shanghai",
        jd_raw="Build document agents and evaluate generated research reports.",
        url="https://jobs.example.test/role", collected_at=datetime(2026, 10, 26, tzinfo=UTC),
    ))
    SqliteJobRepository(db).save_job(job)
    target = GreetingJob(
        job_id=job.id, company=job.company, title=job.title, platform=job.source,
        url=str(job.url), jd_raw=job.jd_raw,
    )
    text = "Hello, I built research agents. May we talk?"
    binding = OutreachSourceBinding(
        candidate_id="CAND_TEST", evidence_ids=[item.id for item in evidence],
        evidence_digest=content_digest([item.model_dump(mode="json") for item in evidence]),
        job_digest=content_digest(target.model_dump(mode="json")),
        text_digest=content_digest(text),
        policy_digest=content_digest(read_reference("references/greeting-ai.md")),
    )
    draft = OutreachDraft(
        job_id=job.id, platform=job.source, text=text, evidence_ids=["EVID_A"],
        variant="whole-message.v1", source_binding=binding,
    )
    return db, candidates, job, draft


def test_bound_sources_match_snapshot_order_without_writing(sources):
    db, _, _, draft = sources
    before = hashlib.sha256(db.path.read_bytes()).hexdigest()
    verify_greeting_sources(db, [draft], candidate_id="CAND_TEST")
    assert hashlib.sha256(db.path.read_bytes()).hexdigest() == before


def test_send_time_can_use_candidate_from_binding_for_item(sources):
    db, _, job, draft = sources
    item = OutreachItem(
        number=1, job_id=job.id, platform=job.source, company=job.company, title=job.title,
        url=str(job.url), text=draft.text, evidence_ids=draft.evidence_ids,
        source_binding=draft.source_binding, variant=draft.variant, item_digest="sha256:fixture",
    )
    verify_greeting_sources(db, [item])


def test_candidate_mismatch_cannot_reuse_another_owner_binding(sources):
    db, _, _, draft = sources
    with pytest.raises(StaleApprovalError):
        verify_greeting_sources(db, [draft], candidate_id="CAND_OTHER")


@pytest.mark.parametrize("change", ["statement", "unconfirmed", "weak", "missing"])
def test_changed_or_missing_same_id_evidence_rejects_without_payload(sources, change):
    db, candidates, _, draft = sources
    item = candidates.get_evidence("CAND_TEST", "EVID_A")
    assert item is not None
    if change == "missing":
        with sqlite3.connect(db.path) as conn:
            conn.execute("DELETE FROM evidence_items WHERE evidence_id = ?", (item.id,))
    else:
        updates = {"statement": "Confidential changed source statement."}
        if change == "unconfirmed":
            updates = {"user_confirmed": False}
        elif change == "weak":
            updates = {"user_confirmed": False, "confidence": Confidence.WEAK}
        candidates.upsert_evidence("CAND_TEST", item.model_copy(update=updates))
    with pytest.raises(StaleApprovalError) as caught:
        verify_greeting_sources(db, [draft])
    assert "Confidential changed source statement" not in str(caught.value)


def test_same_id_jd_change_rejects(sources):
    db, _, job, draft = sources
    SqliteJobRepository(db).save_job(job.model_copy(update={"jd_raw": "Changed role duties."}))
    with pytest.raises(StaleApprovalError):
        verify_greeting_sources(db, [draft])


def test_current_policy_change_rejects(sources, monkeypatch):
    db, _, _, draft = sources
    monkeypatch.setattr("jobagent.bridge.greeting_freshness.read_reference", lambda _: "changed")
    with pytest.raises(StaleApprovalError):
        verify_greeting_sources(db, [draft])


def test_changed_text_or_foreign_claim_reference_rejects(sources):
    db, _, _, draft = sources
    for changed in [draft.model_copy(update={"text": "Unreviewed extra claim."}),
                    draft.model_copy(update={"evidence_ids": ["EVID_FOREIGN"]})]:
        with pytest.raises(StaleApprovalError):
            verify_greeting_sources(db, [changed])


def test_new_pipeline_cannot_drop_source_binding(sources):
    db, _, _, draft = sources
    with pytest.raises(StaleApprovalError):
        verify_greeting_sources(db, [draft.model_copy(update={"source_binding": None})])


def test_legacy_drafts_remain_compatible_without_database_access(tmp_path):
    db = Database(tmp_path / "does-not-exist.sqlite3")
    draft = OutreachDraft(job_id="JOB_LEGACY", platform="manual", text="Legacy draft")
    verify_greeting_sources(db, [draft])
    assert not db.path.exists()


def test_missing_database_does_not_get_created(sources, tmp_path):
    _, _, _, draft = sources
    db = Database(tmp_path / "missing.sqlite3")
    with pytest.raises(StaleApprovalError):
        verify_greeting_sources(db, [draft])
    assert not db.path.exists()
