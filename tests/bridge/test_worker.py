from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jobagent.bridge.worker import WorkerGateway
from jobagent.errors import (
    ApprovalRequiredError,
    ContractValidationError,
    StaleApprovalError,
    StorageError,
)
from jobagent.outreach.service import OutreachService
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.outreach import OutreachDraft, OutreachResult
from jobagent.schemas.sources import HostBrowserSpec, SourceKind, SourceManifest
from jobagent.schemas.worker import WorkerFetchRequest, WorkerReadback
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

NOW = datetime(2026, 10, 23, 3, tzinfo=UTC)
TEXT = "Hello, this is a synthetic approved greeting."
MANIFEST = SourceManifest(
    id="local_test",
    display_name="Synthetic local page",
    kind=SourceKind.FIXTURE,
    host_browser=HostBrowserSpec(
        search_url="http://127.0.0.1:18765/?query={query}",
        detail_url_prefixes=["http://127.0.0.1:18765/"],
        stop_markers=["TEST_LOGIN_REQUIRED"],
    ),
)


def record() -> SourceJobRecord:
    return SourceJobRecord(
        source="local_test", completeness="full", access_state="public",
        source_job_id="TEST_JOB_001",
        title="Test role",
        company="Local test company",
        location="Local",
        collected_at=NOW,
        jd_raw="Synthetic job description for browser ingestion and evidence testing only.",
        url="http://127.0.0.1:18765/",
        search_term="synthetic",
    )


def gateway(tmp_path: Path) -> WorkerGateway:
    db = Database(tmp_path / "worker.sqlite3")
    db.migrate()
    return WorkerGateway(db, manifests=[MANIFEST], clock=lambda: NOW)


def request() -> WorkerFetchRequest:
    return WorkerFetchRequest(task_id="WFETCH_TEST", worker_id="W1", observations=[record()])


def prepare(gw: WorkerGateway, *, approve: bool = True, lease: bool = True) -> str:
    imported = gw.ingest(request())
    jobs = SqliteJobRepository(gw.database)
    job = jobs.get_job(imported.report.stored[0].job_id)
    assert job is not None
    svc = OutreachService()
    batch = svc.build_batch(
        [OutreachDraft(job_id=job.id, platform="local_test", text=TEXT)],
        jobs={job.id: job},
        already_contacted=[],
        confirmed_evidence_ids=[],
        batch_id="OBATCH_TEST",
        created_at=NOW,
    ).batch
    assert batch is not None
    store = SqliteOutreachRepository(gw.database)
    store.save_batch(batch)
    ask = svc.ask(batch, asked_at=NOW)
    store.save_ask(ask)
    if approve:
        store.save_approval(
            svc.approve(
                batch,
                ask=ask,
                numbers=[1],
                attestation="Synthetic fixture consent only",
                approved_at=NOW,
            )
        )
    if lease:
        assert store.acquire_lease("local_test", "W1", now=NOW, ttl_seconds=1800)
    return batch.batch_id


def test_fetch_commits_jobs_and_small_event_and_replays_without_duplicates(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    first = gw.ingest(request())
    assert first.status == "stored" and len(first.report.stored) == 1
    assert gw.ingest(request()) == first
    assert gw.show(first.task_id) == first
    assert len(SqliteJobRepository(gw.database).list_jobs()) == 1
    assert len(SqliteJobRepository(gw.database).search_hits()) == 1
    events = gw.events()
    assert len(events) == 1 and events[0].job_ids == [first.report.stored[0].job_id]
    assert record().jd_raw not in events[0].model_dump_json()
    gw.acknowledge(events[0].event_id)
    gw.acknowledge(events[0].event_id)
    assert gw.events() == []


def test_same_task_id_with_other_input_is_rejected(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    gw.ingest(request())
    changed = request().model_copy(
        update={"observations": [record().model_copy(update={"company": "Changed"})]}
    )
    with pytest.raises(ContractValidationError, match="different input"):
        gw.ingest(changed)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"url": "https://example.com/not-the-board"}, "url_outside_board"),
        ({"jd_raw": "TEST_LOGIN_REQUIRED" * 4}, "gate_page"),
        ({"jd_raw": "short"}, "jd_too_short"),
        ({"source": "not_registered"}, "no_host_route"),
    ],
)
def test_rejected_observations_never_become_jobs(
    tmp_path: Path, change: dict[str, str], reason: str
) -> None:
    gw = gateway(tmp_path)
    item = SourceJobRecord.model_validate({**record().model_dump(), **change})
    result = gw.ingest(request().model_copy(update={"observations": [item]}))
    assert result.status == "rejected" and result.report.rejected[0].reason == reason
    assert SqliteJobRepository(gw.database).list_jobs() == []


def test_event_failure_rolls_back_the_entire_fetch(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    with gw.database.connect() as c, c:
        c.execute(
            "CREATE TRIGGER reject_event BEFORE INSERT ON worker_events "
            "BEGIN SELECT RAISE(ABORT, 'test event failure'); END"
        )
    with pytest.raises(StorageError):
        gw.ingest(request())
    assert SqliteJobRepository(gw.database).list_jobs() == []
    assert gw.show("WFETCH_TEST") is None


def test_claim_requires_human_approval_and_platform_lease(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw, approve=False)
    with pytest.raises(ApprovalRequiredError):
        gw.claim_greeting(batch_id, "local_test", "W1")


def test_claim_without_lease_is_refused(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw, lease=False)
    with pytest.raises(ContractValidationError, match="lease_not_held"):
        gw.claim_greeting(batch_id, "local_test", "W1")


def test_only_one_concurrent_claim_can_release_the_exact_text(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw)

    def claim() -> str:
        try:
            return gw.claim_greeting(batch_id, "local_test", "W1").item.text
        except ContractValidationError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == sorted([TEXT, "refused"])


def test_changed_job_invalidates_approved_content(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw)
    jobs = SqliteJobRepository(gw.database)
    job = jobs.list_jobs()[0]
    jobs.save_job(job.model_copy(update={"jd_raw": job.jd_raw + " changed"}))
    with pytest.raises(StaleApprovalError):
        gw.claim_greeting(batch_id, "local_test", "W1")


def test_payload_tampering_is_detected_even_with_original_digest_fields(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw)
    with gw.database.connect() as c, c:
        c.execute(
            "UPDATE outreach_batches SET batch_json = json_set("
            "batch_json, '$.items[0].text', 'tampered') WHERE batch_id = ?",
            (batch_id,),
        )
    with pytest.raises(StaleApprovalError):
        gw.claim_greeting(batch_id, "local_test", "W1")


def test_exact_readback_records_once_and_completes_event(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    authorized = gw.authorize_greeting(claim.task_id, "W1")
    assert authorized.item == claim.item and authorized.state == "authorized"
    with pytest.raises(ContractValidationError):
        gw.authorize_greeting(claim.task_id, "W1")
    readback = WorkerReadback(
        task_id=claim.task_id,
        worker_id="W1",
        result="sent",
        observed_url=claim.item.url,
        observed_text=TEXT,
    )
    receipt = gw.record_greeting(readback)
    assert receipt.result is OutreachResult.SENT
    assert gw.record_greeting(readback) == receipt
    assert len(SqliteOutreachRepository(gw.database).list_audits()) == 1
    assert gw.show(claim.task_id) == receipt
    assert len(gw.events()) == 2
    with pytest.raises(ContractValidationError):
        gw.authorize_greeting(claim.task_id, "W1")


@pytest.mark.parametrize(
    "text,url,result",
    [
        (None, None, "unknown"),
        ("different", "http://127.0.0.1:18765/", "sent"),
        (TEXT, "http://127.0.0.1:18765/wrong", "sent"),
    ],
)
def test_uncertain_or_mismatched_readback_halts_instead_of_retrying(
    tmp_path: Path, text: str | None, url: str | None, result: str
) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    readback = WorkerReadback.model_validate(
        {
            "task_id": claim.task_id,
            "worker_id": "W1",
            "result": result,
            "observed_text": text,
            "observed_url": url,
        }
    )
    receipt = gw.record_greeting(readback)
    assert receipt.result is OutreachResult.INTERVENTION
    assert receipt.observed_result == result
    assert (
        SqliteOutreachRepository(gw.database).list_audits()[0].result is OutreachResult.INTERVENTION
    )


def test_another_worker_cannot_complete_a_claim_and_expiry_never_releases_again(
    tmp_path: Path,
) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    with pytest.raises(ContractValidationError):
        gw.record_greeting(WorkerReadback(task_id=claim.task_id, worker_id="W2", result="unknown"))
    later = WorkerGateway(gw.database, manifests=[MANIFEST], clock=lambda: NOW + timedelta(hours=1))
    store = SqliteOutreachRepository(gw.database)
    assert store.acquire_lease("local_test", "W2", now=NOW + timedelta(hours=1), ttl_seconds=1800)
    with pytest.raises(ContractValidationError):
        later.claim_greeting(claim.batch_id, "local_test", "W2")


def test_completion_event_failure_rolls_back_send_audit(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    with gw.database.connect() as c, c:
        c.execute(
            "CREATE TRIGGER reject_event BEFORE INSERT ON worker_events "
            "BEGIN SELECT RAISE(ABORT, 'test event failure'); END"
        )
    with pytest.raises(StorageError):
        gw.record_greeting(WorkerReadback(task_id=claim.task_id, worker_id="W1", result="unknown"))
    assert SqliteOutreachRepository(gw.database).list_audits() == []
    assert gw.show(claim.task_id) == claim


def test_an_approval_without_the_original_question_does_not_release_content(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    batch_id = prepare(gw)
    with gw.database.connect() as c, c:
        c.execute("DELETE FROM outreach_asks")
    with pytest.raises(ApprovalRequiredError):
        gw.claim_greeting(batch_id, "local_test", "W1")


def test_sent_report_without_dispatch_authorization_is_intervention(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    receipt = gw.record_greeting(
        WorkerReadback(
            task_id=claim.task_id,
            worker_id="W1",
            result="sent",
            observed_url=claim.item.url,
            observed_text=TEXT,
        )
    )
    assert receipt.result is OutreachResult.INTERVENTION


def test_a_changed_gate_during_execution_still_records_an_intervention(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    gw.authorize_greeting(claim.task_id, "W1")
    SqliteOutreachRepository(gw.database).withdraw(claim.batch_id, "synthetic withdrawal", NOW)
    receipt = gw.record_greeting(
        WorkerReadback(
            task_id=claim.task_id,
            worker_id="W1",
            result="sent",
            observed_url=claim.item.url,
            observed_text=TEXT,
        )
    )
    assert receipt.result is OutreachResult.INTERVENTION
    assert receipt.observed_result == "sent"
    assert "gate_changed" in receipt.reason


def test_a_completed_task_never_accepts_a_changed_readback(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    claim = gw.claim_greeting(prepare(gw), "local_test", "W1")
    gw.record_greeting(WorkerReadback(task_id=claim.task_id, worker_id="W1", result="unknown"))
    with pytest.raises(ContractValidationError):
        gw.record_greeting(WorkerReadback(task_id=claim.task_id, worker_id="W1", result="failed"))


def test_mixed_fetch_commits_only_accepted_observations(tmp_path: Path) -> None:
    gw = gateway(tmp_path)
    req = request().model_copy(
        update={
            "observations": [
                record(),
                record().model_copy(update={"source_job_id": "second", "jd_raw": "short"}),
            ]
        }
    )
    receipt = gw.ingest(req)
    assert receipt.status == "partial"
    assert len(receipt.report.stored) == len(receipt.report.rejected) == 1
