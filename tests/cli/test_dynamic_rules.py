import json

from typer.testing import CliRunner

from jobagent.cli.app import app
from tests.rules.test_dynamic_registry import request


def test_cli_parameter_proposal_approval_export_and_notice(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(request().model_dump_json(), encoding="utf-8")
    db = str(tmp_path / "rules.sqlite3")
    runner = CliRunner()
    proposed = runner.invoke(app, ["rules", "propose", str(path), "--database", db])
    assert proposed.exit_code == 0, proposed.stdout
    proposal = json.loads(proposed.stdout)
    result = runner.invoke(
        app,
        [
            "rules",
            "approve",
            proposal["proposal_id"],
            "--candidate",
            "CAND_SYNTHETIC",
            "--question-digest",
            proposal["question_digest"],
            "--answer",
            "Synthetic owner approval",
            "--actor",
            "synthetic owner",
            "--database",
            db,
        ],
    )
    assert result.exit_code == 0, result.stdout
    exported = tmp_path / ".jobagent" / "effective.json"
    effective = runner.invoke(
        app, ["rules", "effective", "CAND_SYNTHETIC", "--output", str(exported), "--database", db]
    )
    data = json.loads(effective.stdout)
    assert len(data["pending_changes"]) == 1
    assert json.loads(exported.read_text())["values"]["ABANDON_HOURS"] == 72
    assert data["snapshot"]["version"] == json.loads(exported.read_text())["version"]


def test_rules_propose_does_not_activate(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(request().model_dump_json(), encoding="utf-8")
    db = str(tmp_path / "rules.sqlite3")
    runner = CliRunner()
    assert runner.invoke(app, ["rules", "propose", str(path), "--database", db]).exit_code == 0
    effective = runner.invoke(app, ["rules", "effective", "CAND_SYNTHETIC", "--database", db])
    assert effective.exit_code != 0


def test_read_budget_cli_uses_dynamic_cap_and_reports_version(tmp_path):
    from tests.rules.test_evaluation import profile

    private = tmp_path / ".jobagent"
    private.mkdir()
    rules = profile({"DETAIL_CAP_PER_DAY": 2})
    path = private / "snapshot.json"
    path.write_text(rules.model_dump_json())
    outcome = CliRunner().invoke(
        app,
        [
            "jobs",
            "sourcing-budget",
            "--rules-file",
            str(path),
            "--candidate",
            "CAND_SYNTHETIC",
            "--database",
            str(private / "db.sqlite3"),
        ],
    )
    assert outcome.exit_code == 0, outcome.stdout
    data = json.loads(outcome.stdout)
    assert data["zhaopin"]["daily_cap"] == 2
    assert data["zhaopin"]["rules_version"] == rules.version


def test_dynamic_query_count_can_exceed_legacy_default_without_silent_clipping(tmp_path):
    from tests.rules.test_evaluation import profile

    private = tmp_path / ".jobagent"
    private.mkdir()
    rules = profile({"QUERIES_PER_SITE_PER_ROUND": 7})
    path = private / "snapshot.json"
    path.write_text(rules.model_dump_json())
    context = private / "context.json"
    context.write_text(
        json.dumps(
            {
                "candidate_id": "CAND_SYNTHETIC",
                "preferred_search_terms": [f"Synthetic {i}" for i in range(10)],
            }
        )
    )
    result = CliRunner().invoke(
        app,
        [
            "jobs",
            "search-plan",
            "--filter-context",
            str(context),
            "--rules-file",
            str(path),
            "--candidate",
            "CAND_SYNTHETIC",
            "--database",
            str(private / "db.sqlite3"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert len(data["plans"]["zhaopin"]["chosen"]) == 7
    assert data["rules_version"] == rules.version


def test_salary_filter_reports_bound_dynamic_version(tmp_path):
    from jobagent.schemas.common import MoneyRange
    from jobagent.schemas.job_intelligence import CandidateFilterContext
    from tests.cli.test_jobs import reviewed_files
    from tests.rules.test_evaluation import profile

    snapshot = profile({"SALARY_FLOOR_K": 700, "SALARY_COMPARE_MODE": "upper_bound"})
    rules_file = tmp_path / ".jobagent" / "rules.json"
    rules_file.parent.mkdir()
    rules_file.write_text(snapshot.model_dump_json())
    requirements, _, _ = reviewed_files(tmp_path)
    context_file = tmp_path / "context.json"
    context_file.write_text(
        CandidateFilterContext(
            candidate_id="CAND_SYNTHETIC",
            minimum_compensation=MoneyRange(currency="DKK", minimum=1000, period="year"),
        ).model_dump_json()
    )
    result = CliRunner().invoke(
        app,
        [
            "jobs",
            "filter",
            "alpha-001",
            str(requirements),
            str(context_file),
            "--rules-file",
            str(rules_file),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["rules_version"] == snapshot.version
