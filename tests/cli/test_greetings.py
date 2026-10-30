import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.greetings import greetings_app
from jobagent.errors import UserInterventionRequiredError
from jobagent.outreach.generation import GreetingGenerator, content_digest
from jobagent.schemas.greeting import GreetingRequest
from jobagent.storage.database import Database


def setup(tmp_path: Path, monkeypatch, *, targeted=False):
    monkeypatch.chdir(tmp_path)
    private = tmp_path / "candidate" / "private"
    private.mkdir(parents=True)
    settings = private / "settings.json"
    settings.write_text(json.dumps({"candidate_id": "CAND_TEST", "display_name": "Alex"}))
    database = private / "db.sqlite3"
    Database(database).migrate()
    job = {
        "job_id": "JOB_TEST",
        "company": "Synthetic",
        "title": "AI PM",
        "platform": "manual",
        "url": "https://jobs.example.test/test",
        "jd_raw": "Build report agents.",
    }
    request = GreetingRequest.model_validate(
        {
            "candidate_id": "CAND_TEST",
            "display_name": "Alex",
            "policy_digest": content_digest("Policy"),
            "mode": "targeted" if targeted else "default",
            "job": job if targeted else None,
            "interests": [{"job": job, "selection_id": "OAPPROVAL_TEST"}],
            "evidence": [
                {
                    "id": "EVID_TEST",
                    "type": "project",
                    "statement": "Built agents.",
                    "confidence": "explicit",
                    "user_confirmed": True,
                    "source": {"type": "interview", "reference": "CHAT_TEST"},
                }
            ],
        }
    )
    monkeypatch.setattr("jobagent.cli.greetings.load_greeting_request", lambda *a, **k: request)
    monkeypatch.setattr("jobagent.cli.greetings._find_executable", lambda p: "codex.exe")
    monkeypatch.setattr("jobagent.cli.greetings.CodexGreetingProvider", lambda r: Provider())
    return settings, database


class Provider:
    def generate(self, *, prompt_id, context, output_type):
        if "draft" in prompt_id:
            return output_type.model_validate(
                {
                    "input_digest": context["input_digest"],
                    "text": "Hello, I built agents. Can we talk?",
                    "angle": "Relevant product work",
                    "claims": [{"text": "I built agents", "evidence_ids": ["EVID_TEST"]}],
                    "jd_spans": ["Build report agents."] if context["request"]["job"] else [],
                }
            )
        return output_type.model_validate(
            {
                "input_digest": context["input_digest"],
                "draft_digest": context["draft_digest"],
                "claims": [
                    {"text": "I built agents", "verdict": "supported", "reason": "Evidence"}
                ],
                "full_text_supported": True,
                "no_missing_claims": True,
                "target_relevant": True,
                "style_ok": True,
                "conflicts_resolved": True,
            }
        )


def invoke(settings, database, output, *extra):
    return CliRunner().invoke(
        greetings_app,
        [
            "--candidate",
            "CAND_TEST",
            "--settings",
            str(settings),
            "--database",
            str(database),
            "--output",
            str(output),
            *extra,
        ],
    )


def test_default_cli_writes_private_report_without_body_or_database_mutation(tmp_path, monkeypatch):
    settings, database = setup(tmp_path, monkeypatch)
    before = database.read_bytes()
    output = settings.parent / "generated"
    result = invoke(settings, database, output)
    assert result.exit_code == 0, result.stdout
    assert (output / "report.json").is_file() and (output / "request.json").is_file()
    assert not (output / "drafts.json").exists()
    assert "Hello" not in result.stdout
    assert json.loads(result.stdout)["status"] == "passed"
    assert database.read_bytes() == before


def test_dynamic_writing_preferences_reach_request_and_report(tmp_path, monkeypatch):
    from tests.rules.test_evaluation import profile

    settings, database = setup(tmp_path, monkeypatch)
    snapshot = profile({"GREETING_LEN_SHORT": [100, 170]}, candidate_id="CAND_TEST")
    rules_file = settings.parent / "rules.json"
    rules_file.write_text(snapshot.model_dump_json(), encoding="utf-8")
    output = settings.parent / "dynamic-generated"
    result = invoke(settings, database, output, "--rules-file", str(rules_file))
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["dynamic_rules_version"] == snapshot.version
    saved = json.loads((output / "request.json").read_text(encoding="utf-8"))
    assert snapshot.version in " ".join(saved["guidance"])
    assert "100" in " ".join(saved["guidance"])


def test_targeted_cli_exports_only_draft_not_approval(tmp_path, monkeypatch):
    settings, database = setup(tmp_path, monkeypatch, targeted=True)
    output = settings.parent / "targeted"
    result = invoke(settings, database, output, "--job", "JOB_TEST")
    assert result.exit_code == 0, result.stdout
    drafts = json.loads((output / "drafts.json").read_text())
    assert drafts[0]["job_id"] == "JOB_TEST"
    assert drafts[0]["written_by"] == "agent"
    assert sorted(x.name for x in output.iterdir()) == [
        "drafts.json",
        "report.json",
        "request.json",
    ]


def test_public_output_and_candidate_mismatch_are_rejected(tmp_path, monkeypatch):
    settings, database = setup(tmp_path, monkeypatch)
    result = invoke(settings, database, tmp_path / "docs" / "public")
    assert result.exit_code == 1 and "CONTRACT_VALIDATION_ERROR" in result.stdout
    settings.write_text(json.dumps({"candidate_id": "CAND_OTHER", "display_name": "Other"}))
    result = invoke(settings, database, settings.parent / "wrong")
    assert result.exit_code == 1 and "CONTRACT_VALIDATION_ERROR" in result.stdout


def test_model_failure_is_reported_without_template_fallback(tmp_path, monkeypatch):
    settings, database = setup(tmp_path, monkeypatch)

    def fail(self, request):
        raise UserInterventionRequiredError("Model timeout")

    monkeypatch.setattr(GreetingGenerator, "generate", fail)
    output = settings.parent / "failed"
    result = invoke(settings, database, output)
    assert result.exit_code == 1 and "USER_INTERVENTION_REQUIRED" in result.stdout
    assert not (output / "drafts.json").exists()


def test_path_traversal_and_reusing_output_are_rejected(tmp_path, monkeypatch):
    settings, database = setup(tmp_path, monkeypatch)
    escaping = settings.parent / ".." / ".." / "public"
    result = invoke(settings, database, escaping)
    assert result.exit_code == 1 and not (tmp_path / "public").exists()
    output = settings.parent / "existing"
    output.mkdir()
    prior = output / "drafts.json"
    prior.write_text("Do not replace this approved draft.")
    result = invoke(settings, database, output)
    assert result.exit_code == 1 and "new output directory" in result.stdout
    assert prior.read_text() == "Do not replace this approved draft."
