from datetime import UTC, timedelta
from pathlib import Path

import pytest

from jobagent.errors import StorageError
from jobagent.outreach.service import OutreachService
from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.outreach import OutreachAudit, OutreachResult
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.outreach.test_service import JOBS, NOW, build, draft


def repository(tmp_path: Path) -> SqliteOutreachRepository:
    database = Database(tmp_path / "jobagent.sqlite3")
    database.migrate()
    return SqliteOutreachRepository(database)


def test_batch_ask_and_approval_round_trip(tmp_path: Path) -> None:
    store = repository(tmp_path)
    service = OutreachService()
    batch = build([draft(0), draft(1)]).batch
    assert batch is not None
    ask = service.ask(batch, asked_at=NOW)
    approval = service.approve(batch, ask=ask, numbers=[1], attestation="发 1", approved_at=NOW)

    store.save_batch(batch)
    store.save_ask(ask)
    store.save_approval(approval)

    assert store.get_batch(batch.batch_id) == batch
    assert store.get_ask(ask.ask_id) == ask
    assert store.get_approval(batch.batch_id) == approval
    assert store.get_batch("OBATCH_MISSING") is None


def test_audit_is_append_only_and_one_per_item(tmp_path: Path) -> None:
    store = repository(tmp_path)
    batch = build([draft(0)]).batch
    assert batch is not None
    item = batch.items[0]
    audit = OutreachAudit(
        audit_id="OAUDIT_1",
        batch_id=batch.batch_id,
        number=1,
        job_id=item.job_id,
        platform=item.platform,
        item_digest=item.item_digest,
        approval_id="OAPPROVAL_001",
        approval_channel=ApprovalChannel.AGENT_RELAY,
        result=OutreachResult.SENT,
        recorded_at=NOW,
    )

    store.append_audit(audit)
    with pytest.raises(StorageError):
        store.append_audit(audit.model_copy(update={"audit_id": "OAUDIT_2"}))

    assert store.list_audits() == [audit]
    assert not hasattr(store, "update_audit") and not hasattr(store, "delete_audit")
    assert set(JOBS) >= {audit.job_id}


def test_a_platform_lease_belongs_to_one_session_until_it_expires(tmp_path: Path) -> None:
    store = repository(tmp_path)

    assert store.acquire_lease("boss", "S1", now=NOW, ttl_seconds=1800)
    assert not store.acquire_lease("boss", "S2", now=NOW + timedelta(minutes=10), ttl_seconds=1800)
    assert store.acquire_lease("zhaopin", "S2", now=NOW, ttl_seconds=1800)
    assert store.holds_lease("boss", "S1", now=NOW + timedelta(minutes=10))
    assert not store.holds_lease("boss", "S2", now=NOW + timedelta(minutes=10))

    # Renewing keeps it; a stranger cannot release it; expiry frees it.
    assert store.acquire_lease("boss", "S1", now=NOW + timedelta(minutes=20), ttl_seconds=1800)
    assert not store.release_lease("boss", "S2")
    later = NOW + timedelta(minutes=60)
    assert store.acquire_lease("boss", "S2", now=later, ttl_seconds=1800)
    assert store.release_lease("boss", "S2")
    assert not store.holds_lease("boss", "S2", now=later.astimezone(UTC))
