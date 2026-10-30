from datetime import UTC, datetime, timedelta

import pytest

from jobagent.connectors.observations import check_observation
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.sources import SourceRegistry
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


def record(**changes):
    data = dict(
        source="zhaopin", source_job_id="SYNTHETIC_ROLE", title="Research Scientist",
        company="Synthetic Labs", location="Shanghai",
        jd_raw="Research reliable methods.\n\nDesign and evaluate controlled experiments.",
        url="https://www.zhaopin.com/jobdetail/synthetic", collected_at=datetime.now(UTC),
        completeness="full", access_state="public",
    )
    return SourceJobRecord(**(data | changes))


def test_panel_without_detail_link_has_explicit_identity_and_capture_provenance():
    data = record().model_dump(mode="json") | {
        "url": "https://www.zhaopin.com/jobs/?kw=research", "capture_kind": "panel",
        "panel_locator": "platform-job-id:SYNTHETIC_ROLE", "completeness": "full",
        "access_state": "authenticated",
        "panel_source_job_id": "SYNTHETIC_ROLE", "read_attempt_id": "SYN_PANEL_READ",
    }
    manifests = {m.id: m for m in SourceRegistry.default().all()}
    reason, captured = check_observation(data, manifests)
    assert reason == "" and captured is not None


@pytest.mark.parametrize("field,value", [
    ("completeness", "partial"), ("completeness", "unknown"),
    ("access_state", "loading"), ("access_state", "login_required"),
])
def test_partial_or_unavailable_observation_never_enters_normalized_jobs(field, value):
    data = record().model_dump(mode="json") | {field: value}
    reason, captured = check_observation(data, {m.id: m for m in SourceRegistry.default().all()})
    assert captured is None and reason in {"incomplete_jd", "access_unavailable"}


def test_raw_observations_are_append_only_and_latest_view_keeps_identity(tmp_path):
    db = Database(tmp_path / "history.sqlite3")
    db.migrate()
    repo = SqliteJobRepository(db)
    first = record()
    second = record(jd_raw="Develop a different research method.\nPreserve original evidence.",
                    salary_text="20-30k", collected_at=first.collected_at + timedelta(seconds=1))
    one, two = (JobNormalizer("CNY").normalize(r) for r in (first, second))
    assert one.id == two.id
    repo.save_observation(first, one)
    repo.save_observation(first, one)
    repo.save_observation(second, two)
    history = repo.observations(one.id)
    assert len(history) == 2
    assert history[0].record.jd_raw == first.jd_raw
    assert history[0].content_digest != history[1].content_digest
    assert repo.get_job(one.id).jd_raw == two.jd_raw
    with db.connect() as connection, pytest.raises(Exception, match="append only"):
        connection.execute("DELETE FROM job_observations")


def test_missing_capture_state_is_not_promoted_to_full():
    data = record().model_dump(mode="json")
    del data["completeness"]
    del data["access_state"]
    reason, captured = check_observation(data, {m.id: m for m in SourceRegistry.default().all()})
    assert captured is None and reason == "access_unavailable"


def test_panel_observed_identity_must_match_requested_identity():
    data = record().model_dump(mode="json") | {
        "capture_kind": "panel", "url": "https://www.zhaopin.com/jobs/",
        "panel_locator": "#visible-panel", "panel_source_job_id": "ANOTHER_ROLE",
    }
    reason, captured = check_observation(data, {m.id: m for m in SourceRegistry.default().all()})
    assert captured is None and reason == "panel_identity_missing"


def test_one_completed_read_cannot_be_rebound_to_a_different_capture(tmp_path):
    from jobagent.errors import ContractValidationError
    from jobagent.schemas.sourcing import ReadOutcome, ReadReservation
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    db = Database(tmp_path / "read-history.sqlite3")
    db.migrate()
    repo = SqliteJobRepository(db)
    reads = SqliteSourcingRepository(db)
    first = record(read_attempt_id="ONE_READ")
    reads.reserve(ReadReservation(
        attempt_id="ONE_READ", source=first.source, target_url=first.url,
        profile="standard", expected_daily_cap=50,
    ), daily_cap=50, now=first.collected_at)
    reads.record(ReadOutcome(attempt_id="ONE_READ", status="read"), now=first.collected_at)
    repo.save_observation(first, JobNormalizer().normalize(first))
    second = first.model_copy(update={"jd_raw": "An entirely different captured description."})
    with pytest.raises(ContractValidationError, match="already bound"):
        repo.save_observation(second, JobNormalizer().normalize(second))
    import sqlite3

    with db.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO job_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("OTHER_OBSERVATION", JobNormalizer().normalize(first).id, None,
             first.model_dump_json(), JobNormalizer().normalize(first).model_dump_json(),
             "captured", first.collected_at.isoformat()),
        )


def test_current_host_observation_requires_metered_read():
    data = record().model_dump(mode="json")
    reason, captured = check_observation(data, {m.id: m for m in SourceRegistry.default().all()})
    assert captured is None and reason == "read_attempt_missing"
