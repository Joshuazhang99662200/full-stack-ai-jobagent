from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.jobs.test_sent_tracking import NOW, proof


def service(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.host_checks import HostPageService
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository

    db = Database(tmp_path / "private.sqlite3")
    db.migrate()
    tracking = SqliteSentTrackingRepository(db)
    tracking.start(proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_DEMO", now=NOW)
    return HostPageService(db), tracking


def observation(**changes):
    values = dict(
        observation_id="PAGE_ONE",
        candidate_id="CAND_DEMO",
        source="boss",
        surface="messages",
        state="login_redirect",
        observed_at=NOW + timedelta(hours=1),
        evidence_reference="PRIVATE_SCREENSHOT_ONE",
        reload_count=0,
    )
    values.update(changes)
    return values


def test_message_login_loss_pauses_original_state_and_requires_notification(tmp_path):
    pages, tracking = service(tmp_path)
    result = pages.record(observation(), now=NOW + timedelta(hours=1))
    current = tracking.get("TRACK_DEMO", "CAND_DEMO")
    assert current.paused and current.tracking_state == "awaiting_reply"
    assert result["notification_required"] is True and result["needs_user_action"]
    assert result["reply_confirmed"] is False
    assert tracking.due("CAND_DEMO", now=NOW + timedelta(days=2)) == []
    assert pages.record(observation(), now=NOW + timedelta(hours=1)) == result


def test_search_session_does_not_infer_message_login_state(tmp_path):
    pages, tracking = service(tmp_path)
    pages.record(
        observation(surface="messages", state="logged_in", observation_id="PAGE_MSG"),
        now=NOW + timedelta(hours=1),
    )
    result = pages.record(observation(surface="search"), now=NOW + timedelta(hours=1))
    assert result["needs_user_action"] and not tracking.get("TRACK_DEMO", "CAND_DEMO").paused
    statuses = pages.latest("CAND_DEMO")
    assert statuses["boss/messages"]["state"] == "logged_in"
    assert statuses["boss/search"]["state"] == "login_redirect"


def test_placeholder_can_reload_once_then_is_unknown_not_no_reply_or_logged_out(tmp_path):
    pages, tracking = service(tmp_path)
    first = pages.record(observation(state="not_loaded"), now=NOW + timedelta(hours=1))
    assert first["action"] == "reload_once" and not first["needs_user_action"]
    second = pages.record(
        observation(state="not_loaded", reload_count=1, observation_id="PAGE_TWO"),
        now=NOW + timedelta(hours=1),
    )
    assert second["action"] == "unconfirmed" and not second["reply_confirmed"]
    assert not second["login_failure"] and not second["notification_required"]
    assert tracking.get("TRACK_DEMO", "CAND_DEMO").check_count == 0
    assert not tracking.get("TRACK_DEMO", "CAND_DEMO").paused


def test_logged_in_page_does_not_resume_tracking_without_owner_or_confirm_a_reply(tmp_path):
    pages, tracking = service(tmp_path)
    pages.record(observation(), now=NOW + timedelta(hours=1))
    result = pages.record(
        observation(
            observation_id="PAGE_OK", state="logged_in", observed_at=NOW + timedelta(hours=2)
        ),
        now=NOW + timedelta(hours=2),
    )
    assert tracking.get("TRACK_DEMO", "CAND_DEMO").paused
    assert result["reply_confirmed"] is False and result["action"] == "inspect_read_only"


def test_board_statuses_are_independent_and_observation_ids_are_immutable(tmp_path):
    pages, _ = service(tmp_path)
    pages.record(observation(), now=NOW + timedelta(hours=1))
    pages.record(
        observation(observation_id="ZL_PAGE", source="zhilian", state="not_loaded", reload_count=1),
        now=NOW + timedelta(hours=1),
    )
    states = pages.latest("CAND_DEMO")
    assert states["boss/messages"]["state"] == "login_redirect"
    assert states["zhilian/messages"]["state"] == "not_loaded"
    with pytest.raises(ContractValidationError):
        pages.record(observation(state="logged_in"), now=NOW + timedelta(hours=1))
    with pytest.raises(ContractValidationError):
        pages.record(
            observation(observation_id="PAGE_FUTURE", observed_at=NOW + timedelta(days=1)), now=NOW
        )


def test_closed_tracking_is_not_revived_or_paused_by_login_loss(tmp_path):
    pages, tracking = service(tmp_path)
    from tests.jobs.test_sent_tracking import event

    state = tracking.get("TRACK_DEMO", "CAND_DEMO")
    update = event(
        state, "user_abandon", observed_at=NOW, evidence_kind="owner_message", owner_text="停止跟踪"
    )
    closed = tracking.apply(update, now=NOW)
    pages.record(observation(), now=NOW + timedelta(hours=1))
    assert tracking.get("TRACK_DEMO", "CAND_DEMO") == closed


def test_page_order_uses_actual_time_not_timezone_string_sorting(tmp_path):
    pages, _ = service(tmp_path)
    from datetime import timezone

    earlier = NOW + timedelta(hours=1)
    pages.record(
        observation(
            state="logged_in", observed_at=earlier.astimezone(timezone(timedelta(hours=8)))
        ),
        now=NOW + timedelta(hours=2),
    )
    pages.record(
        observation(
            observation_id="ACTUALLY_LATER",
            state="not_loaded",
            reload_count=1,
            observed_at=NOW + timedelta(hours=2),
        ),
        now=NOW + timedelta(hours=2),
    )
    assert pages.latest("CAND_DEMO")["boss/messages"]["observation_id"] == "ACTUALLY_LATER"


def pipeline_service(tmp_path):
    from jobagent.schemas.pipeline import PipelineMeta
    from jobagent.storage.pipeline_repository import PipelineRepository
    from tests.jobs.test_pipeline_contracts import row

    pages, tracking = service(tmp_path)
    pipes = PipelineRepository(pages.database)
    records = []
    for number, platform in enumerate(("boss", "zhaopin"), start=1):
        job = row(
            pipeline_id=f"PIPE_{number:016X}",
            job_id=f"{platform}-synthetic",
            platform=platform,
            entered_at=NOW,
            state_changed_at=NOW,
            updated_at=NOW,
        )
        meta = PipelineMeta(
            pipeline_id=job.pipeline_id, entered_evidence_reference="SYNTHETIC_ENTRY"
        )
        records.append(
            pipes.create(
                job, meta, event_id=f"CREATE_{number}", evidence_reference="SYNTHETIC_ENTRY"
            )
        )
    return pages, tracking, pipes, records


def test_pipeline_login_loss_pauses_only_same_board_and_does_not_mutate_legacy_archive(tmp_path):
    pages, tracking, pipes, records = pipeline_service(tmp_path)
    legacy = tracking.get("TRACK_DEMO", "CAND_DEMO")
    result = pages.record(observation(), now=NOW + timedelta(hours=1))
    assert result["paused_pipeline_ids"] == [records[0][0].pipeline_id]
    assert result["paused_tracking_ids"] == []
    assert pipes.get(records[0][0].pipeline_id, "CAND_DEMO")[1].paused
    assert not pipes.get(records[1][0].pipeline_id, "CAND_DEMO")[1].paused
    assert tracking.get("TRACK_DEMO", "CAND_DEMO") == legacy
    assert pages.record(observation(), now=NOW + timedelta(hours=1)) == result
    assert pipes.get(records[0][0].pipeline_id, "CAND_DEMO")[1].version == 2


def test_pipeline_search_redirect_does_not_pause_messages_or_resume_from_logged_in(tmp_path):
    pages, _, pipes, records = pipeline_service(tmp_path)
    result = pages.record(observation(surface="search"), now=NOW + timedelta(hours=1))
    assert result["paused_pipeline_ids"] == []
    assert not pipes.get(records[0][0].pipeline_id, "CAND_DEMO")[1].paused
    pages.record(observation(observation_id="MESSAGE_LOSS"), now=NOW + timedelta(hours=1))
    pages.record(
        observation(
            observation_id="LOGIN_RECOVERED",
            state="logged_in",
            observed_at=NOW + timedelta(hours=2),
        ),
        now=NOW + timedelta(hours=2),
    )
    assert pipes.get(records[0][0].pipeline_id, "CAND_DEMO")[1].paused


def test_pipeline_login_pause_retries_after_partial_failure_without_duplicate_versions(
    tmp_path, monkeypatch
):
    from jobagent.storage.pipeline_repository import PipelineRepository

    pages, _, pipes, records = pipeline_service(tmp_path)
    first = records[0]
    second_job = first[0].model_copy(
        update={"pipeline_id": "PIPE_0000000000000003", "job_id": "boss-another"}
    )
    second_meta = first[1].model_copy(update={"pipeline_id": second_job.pipeline_id})
    pipes.create(
        second_job, second_meta, event_id="CREATE_ANOTHER", evidence_reference="SYNTHETIC_ENTRY"
    )
    original = PipelineRepository.observe
    failed = False

    def intermittent(self, event, *, now, proof=None):
        nonlocal failed
        if event.pipeline_id == second_job.pipeline_id and not failed:
            failed = True
            raise RuntimeError("Synthetic interruption")
        return original(self, event, now=now, proof=proof)

    monkeypatch.setattr(PipelineRepository, "observe", intermittent)
    with pytest.raises(RuntimeError):
        pages.record(observation(), now=NOW + timedelta(hours=1))
    result = pages.record(observation(), now=NOW + timedelta(hours=1))
    assert set(result["paused_pipeline_ids"]) == {first[0].pipeline_id, second_job.pipeline_id}
    assert pipes.get(first[0].pipeline_id, "CAND_DEMO")[1].version == 2
    assert pipes.get(second_job.pipeline_id, "CAND_DEMO")[1].version == 2
