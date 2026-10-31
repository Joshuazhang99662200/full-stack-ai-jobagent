import json
from datetime import datetime

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.errors import UserInterventionRequiredError
from jobagent.schemas.sourcing import SourcingAttemptRequest
from jobagent.storage.sourcing_repository import SqliteSourcingRepository
from tests.jobs.test_query_selection import listing
from tests.storage.test_configured_sourcing import NOW, configured, intent

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixed_cli_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr("jobagent.cli.jobs.datetime", Clock)
    monkeypatch.setattr("jobagent.cli.sourcing.datetime", Clock)


def reserve_query(db, rules, attempt_id="QUERY_ONE"):
    repo = SqliteSourcingRepository(db)
    repo.start_run(intent(rules), now=NOW, daily_cap=9)
    repo.reserve(
        SourcingAttemptRequest(
            attempt_id=attempt_id,
            run_id="RUN_SYNTH",
            kind="query",
            search_term="synthetic query",
        ),
        now=NOW,
    )


def test_dynamic_start_uses_the_existing_confirmed_profile_without_reprompt(tmp_path):
    db, rules = configured(tmp_path)
    private = tmp_path / ".jobagent"
    private.mkdir()
    snapshot = private / "rules.json"
    snapshot.write_text(rules.model_dump_json(), encoding="utf-8")
    request = private / "start.json"
    request.write_text(
        json.dumps(
            {
                "run_id": "RUN_SYNTH",
                "candidate_id": rules.candidate_id,
                "source": "boss",
            }
        )
    )
    result = runner.invoke(
        app,
        [
            "jobs",
            "sourcing-start",
            str(request),
            "--rules-file",
            str(snapshot),
            "--database",
            str(db.path),
        ],
    )
    assert result.exit_code == 0, result.output
    run = json.loads(result.stdout)
    assert (run["top_per_query"], run["detail_limit"], run["daily_detail_limit"]) == (3, 2, 9)
    assert run["rules_version"] == rules.version


def test_bound_listing_takes_configured_front_rows_and_replay_never_calls_source_again(
    tmp_path,
    monkeypatch,
):
    db, rules = configured(tmp_path)
    reserve_query(db, rules)
    calls = []

    class FakeSource:
        def search_listings(self, query):
            calls.append(query)
            return [listing(i) for i in range(5)]

    monkeypatch.setattr("jobagent.cli.jobs._listing_source", lambda source: FakeSource())
    argv = [
        "jobs",
        "listings",
        "synthetic query",
        "--source",
        "boss",
        "--database",
        str(db.path),
        "--run-id",
        "RUN_SYNTH",
        "--attempt-id",
        "QUERY_ONE",
    ]
    first = runner.invoke(app, argv)
    assert first.exit_code == 0, first.output
    selection = json.loads(first.stdout)
    assert selection["requested"] == 3 and selection["taken_count"] == 3
    assert len(selection["items"]) == 3 and len(calls) == 1
    again = runner.invoke(app, argv)
    assert again.exit_code == 0 and json.loads(again.stdout) == selection
    assert len(calls) == 1


def test_configured_listing_cannot_fall_back_to_an_unbound_route(tmp_path, monkeypatch):
    db, _ = configured(tmp_path)
    calls = []
    monkeypatch.setattr("jobagent.cli.jobs._listing_source", lambda source: calls.append(source))
    result = runner.invoke(
        app, ["jobs", "listings", "synthetic", "--source", "boss", "--database", str(db.path)]
    )
    assert result.exit_code != 0 and calls == []


def test_cli_sourcing_take_returns_real_shortfall_without_claiming_full_traversal(tmp_path):
    db, rules = configured(tmp_path)
    reserve_query(db, rules)
    path = tmp_path / "capture.json"
    path.write_text(
        json.dumps(
            {
                "attempt_id": "QUERY_ONE",
                "items": [listing(1).model_dump(mode="json")],
                "loaded": True,
                "access_state": "public",
                "next_cursor": "page2",
            }
        )
    )
    result = runner.invoke(app, ["jobs", "sourcing-take", str(path), "--database", str(db.path)])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["shortfall"] == 2 and output["next_cursor"] == "page2"
    assert output["traversal_complete"] is False


def test_actual_provider_gate_stops_round_and_does_not_retry(tmp_path, monkeypatch):
    db, rules = configured(tmp_path)
    reserve_query(db, rules)
    calls = []

    class GatedSource:
        def search_listings(self, query):
            calls.append(query)
            raise UserInterventionRequiredError("Synthetic rate limit")

    monkeypatch.setattr("jobagent.cli.jobs._listing_source", lambda source: GatedSource())
    argv = [
        "jobs",
        "listings",
        "synthetic query",
        "--source",
        "boss",
        "--database",
        str(db.path),
        "--run-id",
        "RUN_SYNTH",
        "--attempt-id",
        "QUERY_ONE",
    ]
    assert runner.invoke(app, argv).exit_code != 0
    assert len(calls) == 1
    assert runner.invoke(app, argv).exit_code != 0 and len(calls) == 1
    assert SqliteSourcingRepository(db).budget("boss", daily_cap=9, now=NOW).halted
