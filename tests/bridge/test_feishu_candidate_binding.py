import json
from pathlib import Path
from typing import Any

import pytest

from jobagent.bridge import feishu_approval, feishu_push
from jobagent.bridge.feishu_paged_approval import load_state
from tests.cli.test_outreach import drafted, invoke


@pytest.mark.parametrize("entrypoint", ["auto", "notify"])
def test_configured_candidate_flows_from_push_to_registered_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str,
) -> None:
    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    (database.parent / "feishu_push.json").write_text(
        json.dumps({"user_id": "ou_synthetic", "candidate_id": "CAND_CONFIGURED"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(feishu_push, "sender_for", lambda _: lambda *_: None)
    monkeypatch.setattr(feishu_push, "lark_card_sender", lambda _: lambda _: "om_configured")
    if entrypoint == "auto":
        report = feishu_push.auto_push(database)
        assert report is not None and report["cards"] == 1
    else:
        code, report = invoke("notify", "feishu", "--database", str(database))
        assert code == 0, report
    state = load_state(database, "om_configured")
    assert state is not None and state.candidate_id == "CAND_CONFIGURED"


def test_unbound_normal_card_is_explicit_and_cannot_be_forged_into_approval(tmp_path: Path) -> None:
    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    captured: list[dict[str, Any]] = []

    def sender(card: dict[str, Any]) -> str:
        captured.append(card)
        return "om_unbound"

    feishu_push.send_cards(database, sender)
    assert "未绑定候选人" in json.dumps(captured[0], ensure_ascii=False)
    outcome = feishu_approval.handle_card_event(database, {
        "event_id": "ev_forged", "operator_id": "ou_owner", "message_id": "om_unbound",
        "action_tag": "button", "action_name": "approve_0_0", "form_value": "{}",
    }, owner="ou_owner")
    assert outcome.status == "rejected" and "候选人" in outcome.lines[0]


@pytest.mark.parametrize("bad", ["", "CAND_wrong", True, {"id": "CAND_A"}])
def test_invalid_candidate_binding_is_not_silently_coerced(tmp_path: Path, bad: object) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"user_id": "ou_test", "candidate_id": bad}), encoding="utf-8")
    with pytest.raises(feishu_push.PushError, match="candidate_id"):
        feishu_push.load_config(path)


def test_configured_push_does_not_revive_evidence_missing_from_current_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from jobagent.outreach.service import OutreachService
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.schemas.outreach import OutreachDraft
    from jobagent.storage.candidate_repository import SqliteCandidateRepository
    from jobagent.storage.database import Database
    from jobagent.storage.job_repository import SqliteJobRepository
    from jobagent.storage.outreach_repository import SqliteOutreachRepository

    database, original_id = drafted(tmp_path)
    db = Database(database)
    store = SqliteOutreachRepository(db)
    original = store.get_batch(original_id)
    assert original is not None
    item = original.items[0]
    job = SqliteJobRepository(db).get_job(item.job_id)
    assert job is not None
    report = OutreachService().build_batch(
        [OutreachDraft(job_id=item.job_id, platform=item.platform, text=item.text,
                       evidence_ids=["EVID_REMOVED"])], jobs={item.job_id: job},
        already_contacted=set(), confirmed_evidence_ids={"EVID_REMOVED"},
        batch_id="OBATCH_PREVIOUS_VALID", created_at=datetime.now(UTC),
    )
    assert report.batch is not None
    batch = report.batch
    store.save_batch(batch)
    store.save_ask(OutreachService().ask(batch))
    SqliteCandidateRepository(db).save_profile(CandidateProfile(id="CAND_CONFIGURED"))
    (database.parent / "feishu_push.json").write_text(
        json.dumps({"user_id": "ou_owner", "candidate_id": "CAND_CONFIGURED"}), encoding="utf-8",
    )
    monkeypatch.setattr(feishu_push, "sender_for", lambda _: lambda *_: None)
    monkeypatch.setattr(feishu_push, "lark_card_sender", lambda _: lambda _: "om_current")
    feishu_push.auto_push(database)
    outcome = feishu_approval.handle_card_event(database, {
        "event_id": "ev_current", "operator_id": "ou_owner", "message_id": "om_current",
        "action_tag": "button", "action_name": "approve_0_0", "form_value": "{}",
    }, owner="ou_owner")
    assert outcome.status == "rejected"
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM outreach_approvals").fetchone()[0] == 0
