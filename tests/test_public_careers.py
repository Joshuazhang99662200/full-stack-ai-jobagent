import json
from datetime import UTC, datetime

import pytest

from jobagent.connectors.public_careers import parse_board
from jobagent.errors import ContractValidationError
from jobagent.schemas.public_careers import PublicCareerBoard, PublicCareerConfig


def board(provider="greenhouse", slug="synthetic"):
    return PublicCareerBoard(provider=provider, board=slug, company="Synthetic employer")


def payload(provider="greenhouse", count=1):
    jobs = []
    for i in range(count):
        jobs.append(
            {
                "id": str(i),
                "title": "Analyst",
                "location": {"name": "Shanghai"},
                "absolute_url": f"https://job-boards.greenhouse.io/synthetic/jobs/{i}",
                "content": "<p>Synthetic full job description</p>",
            }
        )
    if provider == "ashby":
        jobs = [
            {
                "id": "0",
                "title": "Analyst",
                "location": "Remote",
                "jobUrl": "https://jobs.ashbyhq.com/synthetic/0",
                "descriptionPlain": "Synthetic description",
            }
        ]
    return json.dumps({"jobs": jobs}).encode()


def test_board_rejects_path_injection():
    with pytest.raises(ValueError):
        board(slug="../other")


@pytest.mark.parametrize(
    "body",
    [b"{}", b'{"jobs":null}', b'{"success":false,"jobs":[]}', b'{"errors":["denied"],"jobs":[]}'],
)
def test_malformed_is_not_empty(body):
    with pytest.raises(ContractValidationError):
        parse_board(board(), body)


def test_original_identity_and_unknown_jd_are_preserved():
    result = parse_board(board(), payload())
    assert result.raw_returned == 1
    assert result.records[0].observation.completeness == "full"
    assert result.records[0].listing.source == "public_careers:greenhouse:synthetic"
    assert parse_board(board(slug="other"), payload()).records == []
    raw = json.loads(payload())
    raw["jobs"][0].pop("content")
    result = parse_board(board(), json.dumps(raw).encode())
    assert result.records[0].observation is None
    assert result.missing_jd == 1


def test_remote_does_not_imply_china_eligibility():
    from jobagent.jobs.public_careers import region_decision
    from jobagent.schemas.job_intelligence import CandidateFilterContext

    context = CandidateFilterContext(
        candidate_id="CAND_SYNTHETIC", allowed_locations=["China"], remote_allowed=True
    )
    assert region_decision("Remote", context) == "review"
    assert region_decision("London", context) == "reject"


def test_config_requires_explicit_boards_and_candidate_filter():
    with pytest.raises(ValueError):
        PublicCareerConfig(boards=[])


def test_repository_candidate_isolation_and_run_projection(tmp_path):
    from jobagent.schemas.public_careers import PublicCareerRun
    from jobagent.storage.database import Database
    from jobagent.storage.public_careers_repository import SqlitePublicCareersRepository

    database = Database(tmp_path / "synthetic.sqlite3")
    database.migrate()
    repository = SqlitePublicCareersRepository(database)
    run = PublicCareerRun(
        run_id="synthetic",
        candidate_id="CAND_SYNTHETIC",
        rules_version="sha256:synthetic",
        started_at=datetime.now(UTC),
    )
    repository.start(run)
    assert repository.list_runs("CAND_OTHER") == []
    assert repository.list_runs("CAND_SYNTHETIC")[0].status == "running"


def service_fixture(tmp_path, *, body=None, error=None, values=None):
    from jobagent.connectors.public_careers_service import PublicCareersService
    from jobagent.jobs.public_careers import BUDGET_NAMES
    from jobagent.storage.database import Database
    from jobagent.storage.public_careers_repository import SqlitePublicCareersRepository
    from tests.rules.test_evaluation import profile

    database = Database(tmp_path / "synthetic.sqlite3")
    database.migrate()
    rules = profile(
        values or {name: 10000 if name.endswith("BYTES") else 5 for name in BUDGET_NAMES}
    )
    with database.connect() as conn, conn:
        conn.execute(
            "INSERT INTO dynamic_rule_proposals VALUES (?,?,?)",
            ("synthetic", rules.candidate_id, "{}"),
        )
        conn.execute(
            "INSERT INTO dynamic_rule_versions VALUES (?,?,?,?,?)",
            (rules.version, rules.candidate_id, "synthetic", rules.model_dump_json(), "{}"),
        )
        conn.execute(
            "INSERT INTO dynamic_rule_heads VALUES (?,?)", (rules.candidate_id, rules.version)
        )

    class Transport:
        calls = 0

        def get(self, board, *, dispatch, **kwargs):
            dispatch()
            self.calls += 1
            if error:
                raise error
            return body if body is not None else payload()

    transport = Transport()
    repo = SqlitePublicCareersRepository(database)
    return PublicCareersService(repo, transport), repo, rules, transport


def configuration():
    from jobagent.schemas.job_intelligence import CandidateFilterContext

    return PublicCareerConfig(
        boards=[board()],
        filter_context=CandidateFilterContext(
            candidate_id="CAND_SYNTHETIC", allowed_locations=["Shanghai"]
        ),
    )


def test_import_deduplicates_without_creating_contact_rounds(tmp_path):
    from jobagent.storage.job_repository import SqliteJobRepository

    service, repo, rules, transport = service_fixture(tmp_path)
    first = service.run(rules.candidate_id, configuration(), rules, "first")
    second = service.run(rules.candidate_id, configuration(), rules, "second")
    assert first.status == "complete"
    assert second.duplicate == 1
    assert second.http_attempts == second.query_attempts == 1
    assert second.detail_attempts == 0
    assert len(repo.list_records(rules.candidate_id)) == 1
    assert len(SqliteJobRepository(repo.database).list_jobs()) == 1
    with repo.database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM pipeline_jobs").fetchone()[0] == 0
    assert transport.calls == 2


def test_zero_results_failure_truncation_and_cancel_are_distinct(tmp_path):
    service, _repo, rules, transport = service_fixture(tmp_path, body=b'{"jobs":[]}')
    assert service.run(rules.candidate_id, configuration(), rules, "empty").status == "complete"
    cancelled = service.run(
        rules.candidate_id, configuration(), rules, "cancel", cancel=lambda: True
    )
    assert cancelled.status == "cancelled" and cancelled.http_attempts == 0
    service.transport = type(transport)()
    # Invalid payload gets a real request receipt, never a successful zero.
    service.transport.get = lambda board, dispatch, **kw: (dispatch(), b"{}")[1]
    failed = service.run(rules.candidate_id, configuration(), rules, "malformed")
    assert failed.status == "failed" and failed.http_attempts == 1


def test_rate_limit_stop_persists_across_runs(tmp_path):
    from jobagent.errors import UserInterventionRequiredError

    service, _repo, rules, transport = service_fixture(
        tmp_path, error=UserInterventionRequiredError("HTTP 429")
    )
    first = service.run(rules.candidate_id, configuration(), rules, "first")
    second = service.run(rules.candidate_id, configuration(), rules, "second")
    assert first.status == second.status == "paused"
    assert first.http_attempts == 1 and second.http_attempts == 0
    assert transport.calls == 1


def test_missing_budgets_do_not_dispatch_or_start_run(tmp_path):
    service, repo, rules, transport = service_fixture(tmp_path, values={"TOP_PER_QUERY": 3})
    with pytest.raises(ContractValidationError, match="not configured"):
        service.run(rules.candidate_id, configuration(), rules, "blocked")
    assert transport.calls == 0
    assert repo.list_runs(rules.candidate_id) == []


def test_take_limit_reports_all_returned_and_partial(tmp_path):
    from jobagent.jobs.public_careers import BUDGET_NAMES

    values = {name: 10000 if name.endswith("BYTES") else 5 for name in BUDGET_NAMES}
    values["TOP_PER_QUERY"] = 1
    service, _repo, rules, _transport = service_fixture(
        tmp_path, body=payload(count=3), values=values
    )
    run = service.run(rules.candidate_id, configuration(), rules, "limited")
    assert run.status == "partial"
    assert run.raw_returned == run.observed == run.eligible == 3
    assert run.taken == 1 and run.http_attempts == 1 and run.detail_attempts == 0
    assert run.resume_board is not None


def test_daily_channel_budget_does_not_reset_with_new_run(tmp_path):
    from jobagent.jobs.public_careers import BUDGET_NAMES

    values = {name: 10000 if name.endswith("BYTES") else 5 for name in BUDGET_NAMES}
    values["PUBLIC_CAREERS_HTTP_PER_DAY"] = 1
    service, _repo, rules, transport = service_fixture(tmp_path, values=values)
    service.run(rules.candidate_id, configuration(), rules, "first")
    limited = service.run(rules.candidate_id, configuration(), rules, "second")
    assert limited.http_attempts == 0 and limited.status == "failed"
    assert transport.calls == 1


def test_contract_projection_rejects_inconsistent_identity_and_counts():
    from jobagent.schemas.public_careers import PublicCareerRecord, PublicCareerRun

    item = parse_board(board(), payload()).records[0]
    with pytest.raises(ValueError):
        PublicCareerRecord(
            candidate_id="CAND_SYNTHETIC",
            provider="ashby",
            board="synthetic",
            source_job_id="0",
            job_id="JOB_SYNTHETIC",
            run_id="x",
            listing=item.listing,
            region_decision="review",
        )
    with pytest.raises(ValueError):
        PublicCareerRun(
            candidate_id="CAND_SYNTHETIC",
            run_id="x",
            rules_version="sha256:x",
            started_at=datetime.now(),
            taken=-1,
        )


def test_source_manifest_requires_matching_public_api_spec():
    from jobagent.schemas.sources import SourceManifest

    with pytest.raises(ValueError):
        SourceManifest(id="test", display_name="Test", kind="public_api")


def test_provider_pagination_and_missing_jd_are_partial(tmp_path):
    raw = json.loads(payload())
    raw["meta"] = {"total": 2}
    raw["jobs"][0].pop("content")
    service, _repo, rules, _transport = service_fixture(tmp_path, body=json.dumps(raw).encode())
    run = service.run(rules.candidate_id, configuration(), rules, "partial")
    assert run.status == "partial" and run.missing_jd == 1
    assert run.resume_board is not None


def test_same_numeric_job_id_on_different_boards_never_collides():
    from jobagent.connectors.public_careers import identity

    assert identity(board().source, "0") != identity(board(slug="other").source, "0")


def test_stale_rules_are_checked_on_each_dispatch(tmp_path):
    service, repo, rules, transport = service_fixture(tmp_path)
    with repo.database.connect() as conn, conn:
        conn.execute("DELETE FROM dynamic_rule_heads")
    run = service.run(rules.candidate_id, configuration(), rules, "stale")
    assert run.status == "failed" and run.http_attempts == 0
    assert transport.calls == 0


def test_each_input_has_persisted_disposition_and_config(tmp_path):
    from jobagent.jobs.public_careers import BUDGET_NAMES

    values = {name: 10000 if name.endswith("BYTES") else 5 for name in BUDGET_NAMES}
    values["TOP_PER_QUERY"] = 1
    raw = json.loads(payload(count=3))
    raw["jobs"].append({"id": "bad"})
    service, repo, rules, _transport = service_fixture(
        tmp_path, values=values, body=json.dumps(raw).encode()
    )
    service.run(rules.candidate_id, configuration(), rules, "accounted")
    stored = repo.list_runs(rules.candidate_id)[0]
    assert stored.config == configuration()
    assert [item.disposition for item in stored.dispositions] == [
        "taken",
        "deferred",
        "deferred",
        "invalid",
    ]
    assert [item.input_index for item in stored.dispositions] == [0, 1, 2, 3]


def test_geography_does_not_match_chinatown_or_guess_translation():
    from jobagent.jobs.public_careers import region_decision
    from jobagent.schemas.job_intelligence import CandidateFilterContext

    context = CandidateFilterContext(candidate_id="CAND_SYNTHETIC", allowed_locations=["China"])
    assert region_decision("Chinatown", context) != "pass"
    context.allowed_locations = ["上海"]
    assert region_decision("Shanghai", context) == "review"


def test_business_day_is_shanghai_not_utc():
    from jobagent.storage.public_careers_repository import business_day

    assert business_day(datetime(2026, 11, 3, 15, 59, tzinfo=UTC)) == "2026-11-03"
    assert business_day(datetime(2026, 11, 3, 16, 0, tzinfo=UTC)) == "2026-11-04"


def test_business_day_needs_no_optional_timezone_database(monkeypatch):
    import sys
    import zoneinfo

    from jobagent.storage.public_careers_repository import business_day

    original = zoneinfo.TZPATH
    zoneinfo.ZoneInfo.clear_cache()
    zoneinfo.reset_tzpath([])
    for name in ["tzdata", "tzdata.zoneinfo", "tzdata.zoneinfo.Asia"]:
        monkeypatch.setitem(sys.modules, name, None)
    try:
        assert business_day(datetime(2026, 11, 3, 16, 0, tzinfo=UTC)) == "2026-11-04"
    finally:
        zoneinfo.reset_tzpath(original)
        zoneinfo.ZoneInfo.clear_cache()


def test_greenhouse_escaped_html_and_ashby_plain_preserve_text():
    raw = json.loads(payload())
    raw["jobs"][0]["content"] = (
        "&amp;lt;p&amp;gt;First&amp;lt;/p&amp;gt;"
        "&amp;lt;p&amp;gt;Second&amp;lt;/p&amp;gt;"
        "&lt;script&gt;do not include&lt;/script&gt;&lt;style&gt;hidden&lt;/style&gt;"
    )
    text = parse_board(board(), json.dumps(raw).encode()).records[0].observation.jd_raw
    assert text == "First\nSecond"
    raw = json.loads(payload("ashby"))
    raw["jobs"][0]["descriptionPlain"] = "Use versions < 3.10 > 3.0 & keep original."
    text = parse_board(board("ashby"), json.dumps(raw).encode()).records[0].observation.jd_raw
    assert text == "Use versions < 3.10 > 3.0 & keep original."


@pytest.mark.parametrize("posting_id", [None, [], {}, True, 1.5])
def test_invalid_provider_identity_is_not_string_coerced(posting_id):
    raw = json.loads(payload())
    raw["jobs"][0]["id"] = posting_id
    raw["jobs"][0]["absolute_url"] = f"https://job-boards.greenhouse.io/synthetic/jobs/{posting_id}"
    result = parse_board(board(), json.dumps(raw).encode())
    assert result.invalid == 1 and not result.records


def test_later_complete_board_does_not_erase_partial_recovery_point(tmp_path):
    service, _repo, rules, transport = service_fixture(tmp_path)

    def response(selected, *, dispatch, **kwargs):
        dispatch()
        if selected.board == "synthetic":
            return payload(count=6)
        return b'{"jobs":[]}'

    transport.get = response
    config = configuration()
    config.boards.append(board(slug="other"))
    result = service.run(rules.candidate_id, config, rules, "multi")
    assert result.status == "partial"
    assert result.resume_board == board().source


def test_concurrent_stop_is_checked_inside_dispatch_transaction(tmp_path):
    service, repo, rules, transport = service_fixture(tmp_path)

    def stopped_between_checks(selected, *, dispatch, **kwargs):
        repo.stop(rules.candidate_id, selected.provider, "synthetic concurrent gate")
        dispatch()
        transport.calls += 1
        return payload()

    transport.get = stopped_between_checks
    result = service.run(rules.candidate_id, configuration(), rules, "concurrent")
    assert result.status == "paused" and result.http_attempts == 0
    assert transport.calls == 0


def test_gate_stop_is_persisted_before_releasing_inflight_receipt(tmp_path, monkeypatch):
    from jobagent.errors import UserInterventionRequiredError

    service, repo, rules, _transport = service_fixture(
        tmp_path, error=UserInterventionRequiredError("HTTP 403")
    )
    original = repo.finish_http_error

    def checked_finish(receipt, error):
        assert repo.stopped(rules.candidate_id, "greenhouse")
        original(receipt, error)

    monkeypatch.setattr(repo, "finish_http_error", checked_finish)
    result = service.run(rules.candidate_id, configuration(), rules, "gate")
    assert result.status == "paused"
