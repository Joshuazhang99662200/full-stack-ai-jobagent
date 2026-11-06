# ruff: noqa: RUF001  -- synthetic Chinese owner answers are quoted verbatim.
"""Role-play memory evaluation: the generator learns only through recorded feedback."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from jobagent.bridge.roleplay import (
    RoleplayPaths,
    build_report,
    decide_round,
    init_workspace,
    load_scenario,
    run_round,
)
from jobagent.cli.app import app
from jobagent.errors import ContractValidationError
from jobagent.schemas.coordinator import CodexTextRequest
from jobagent.schemas.greeting import GreetingDraft, GreetingReview
from jobagent.schemas.preference_memory import PreferenceApplication, PreferenceUpdate
from jobagent.schemas.roleplay import RoleplayDecision
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)


class StandInModel:
    """Answers like a model would, and remembers every prompt it was shown."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def run(self, request: CodexTextRequest, output_contract):
        body = "".join(record.text for record in request.records)
        self.seen.append(request.instruction + body)
        context = json.loads(body)
        if output_contract is PreferenceUpdate:
            rules = list(context["memory"]["rules"])
            for event in context["events"]:
                if event["reason_category"] == "direction":
                    category, text = "jobs", "不考虑售前和销售类岗位。"
                elif event["action"] == "revise":
                    category, text = "greetings", "开头先讲搭建评测体系的经历，删掉客套话。"
                else:
                    continue
                rules.append({
                    "rule_id": "RULE_" + event["event_id"][-8:], "category": category,
                    "scope": "general", "condition": "任何岗位", "text": text,
                    "source_event_ids": [event["event_id"]], "updated_at": event["occurred_at"],
                })
            return PreferenceUpdate(input_digest=context["input_digest"], rules=rules)
        if output_contract is PreferenceApplication:
            return PreferenceApplication(
                input_digest=context["input_digest"],
                selected_rule_ids=[rule["rule_id"] for rule in context["memory"]["rules"]],
            )
        if output_contract is GreetingDraft:
            statement = context["request"]["evidence"][0]["statement"][:18]
            return GreetingDraft(
                input_digest=context["input_digest"], text=f"您好，我{statement}。能聊聊吗？",
                angle="Evaluation first",
                claims=[{"text": statement,
                         "evidence_ids": [context["request"]["evidence"][0]["id"]]}],
                jd_spans=[context["request"]["job"]["jd_raw"][:12]],
            )
        assert output_contract is GreetingReview
        return GreetingReview(
            input_digest=context["input_digest"], draft_digest=context["draft_digest"],
            claims=[{"text": c["text"], "verdict": "supported", "reason": "Matches evidence"}
                    for c in context["draft"]["claims"]],
            full_text_supported=True, no_missing_claims=True, target_relevant=True,
            style_ok=True, conflicts_resolved=True,
        )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = RoleplayPaths.here()
    init_workspace(paths, load_scenario("evaluation_first_v1"), now=NOW)
    return paths


def decide(paths, number, action, *, revised=None, reason="other", triggered=(), note="合成理由"):
    return decide_round(paths, number, RoleplayDecision(
        action=action, words=f"第 {number} 轮的合成答复", revised_text=revised,
        reason_category=reason, note=note, triggered_preferences=list(triggered),
    ), now=NOW + timedelta(hours=number - 1, minutes=30))


def test_four_rounds_learn_two_hidden_preferences_and_every_invariant_holds(workspace):
    model = StandInModel()
    first = run_round(workspace, model, now=NOW)
    assert first.generation_status == "passed" and first.memory_rule_count == 0
    decide(workspace, 1, "revise", revised="您好，我先说评测：我搭过问答评测集。",
           reason="copy", triggered=["P_EVAL_FIRST"])
    second = run_round(workspace, model, now=NOW + timedelta(hours=1))
    assert second.title == "售前解决方案经理" and second.memory_rule_count == 1
    assert second.selected_rules  # the learned greeting rule shaped this draft
    decide(workspace, 2, "decline", reason="direction", triggered=["P_NO_SALES"])
    run_round(workspace, model, now=NOW + timedelta(hours=2))
    decide(workspace, 3, "approve")
    run_round(workspace, model, now=NOW + timedelta(hours=3))
    decide(workspace, 4, "approve")

    report = build_report(workspace)
    assert {c.check_id: c.passed for c in report.checks} == dict.fromkeys(
        [c.check_id for c in report.checks], True
    ), report.checks
    captured = {p.preference_id: p.captured for p in report.preferences}
    assert captured == {
        "P_EVAL_FIRST": True, "P_NO_PLEASANTRIES": True, "P_ONE_CONCRETE": False,
        "P_NO_SALES": True,
    }
    assert report.actions == {"revise": 1, "decline": 1, "approve": 2, "generation_rejected": 0}
    assert (report.first_half_acceptance, report.second_half_acceptance) == (0.0, 1.0)
    assert report.synthetic_only is True


def test_the_generator_never_sees_the_persona_or_hidden_preferences(workspace):
    model = StandInModel()
    run_round(workspace, model, now=NOW)
    decide(workspace, 1, "revise", revised="您好，我先说评测经历。", reason="copy")
    run_round(workspace, model, now=NOW + timedelta(hours=1))
    scenario = load_scenario("evaluation_first_v1")
    secrets = [scenario.persona, *(p.description for p in scenario.hidden_preferences)]
    assert model.seen and not any(secret in prompt for secret in secrets for prompt in model.seen)


def test_rounds_are_strictly_sequential_and_decisions_grant_no_sending(workspace):
    model = StandInModel()
    run_round(workspace, model, now=NOW)
    with pytest.raises(ContractValidationError, match="Decide the open round"):
        run_round(workspace, model, now=NOW)
    with pytest.raises(ContractValidationError, match="latest round"):
        decide(workspace, 2, "approve")
    with pytest.raises(ContractValidationError, match="hidden preference"):
        decide(workspace, 1, "decline", triggered=["P_UNKNOWN"])
    assert decide(workspace, 1, "decline")["grants_send"] is False
    with pytest.raises(ContractValidationError, match="no open greeting"):
        decide(workspace, 1, "approve")
    store = SqliteOutreachRepository(Database(workspace.database))
    assert store.list_audits() == []


def test_a_workspace_is_initialized_once(workspace):
    with pytest.raises(ContractValidationError, match="fresh directory"):
        init_workspace(workspace, load_scenario("evaluation_first_v1"), now=NOW)


def test_cli_init_persona_and_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    created = runner.invoke(app, ["roleplay", "init", "--scenario", "evaluation_first_v1"])
    assert created.exit_code == 0, created.stdout
    persona = runner.invoke(app, ["roleplay", "persona"])
    assert persona.exit_code == 0 and "P_NO_SALES" in persona.stdout
    report = runner.invoke(app, ["roleplay", "report"])
    assert report.exit_code == 0, report.stdout
    assert json.loads(report.stdout)["rounds"] == 0


FAKE_GEMINI = r'''
import json, sys
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
prompt = sys.stdin.read()
schema_text, task_text = prompt.split("\nTask JSON follows:\n", 1)
title = json.loads(schema_text.split("nothing else:\n", 1)[1])["title"]
task = json.loads(task_text)
context = json.loads("".join(r["text"] for r in task["records"]))
if title == "PreferenceUpdate":
    rules = list(context["memory"]["rules"])
    for event in context["events"]:
        if event["action"] == "revise":
            rules.append({"rule_id": "RULE_" + event["event_id"][-8:], "category": "greetings",
                          "scope": "general", "condition": "any role",
                          "text": "Open with evaluation work; no pleasantries.",
                          "source_event_ids": [event["event_id"]],
                          "updated_at": event["occurred_at"]})
    out = {"input_digest": context["input_digest"], "rules": rules}
elif title == "PreferenceApplication":
    out = {"input_digest": context["input_digest"],
           "selected_rule_ids": [r["rule_id"] for r in context["memory"]["rules"]],
           "search_queries": []}
elif title == "GreetingDraft":
    evidence = context["request"]["evidence"][0]
    claim = evidence["statement"][:18]
    out = {"input_digest": context["input_digest"], "text": "Hi, " + claim + ".",
           "angle": "evaluation", "claims": [{"text": claim, "evidence_ids": [evidence["id"]]}],
           "jd_spans": [context["request"]["job"]["jd_raw"][:12]]}
else:
    out = {"input_digest": context["input_digest"], "draft_digest": context["draft_digest"],
           "claims": [{"text": c["text"], "verdict": "supported", "reason": "matches"}
                      for c in context["draft"]["claims"]],
           "full_text_supported": True, "no_missing_claims": True, "target_relevant": True,
           "style_ok": True, "conflicts_resolved": True, "issues": []}
print(json.dumps({"response": "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```",
                  "stats": {"tools": {"totalCalls": 0}}}))
'''


def test_cli_rounds_through_the_real_gemini_runner_contract(tmp_path, monkeypatch):
    import sys

    monkeypatch.chdir(tmp_path)
    script = tmp_path / "gemini.py"
    script.write_text(FAKE_GEMINI, encoding="utf-8")
    private = tmp_path / ".jobagent"
    private.mkdir()
    config = private / "gemini.json"
    config.write_text(
        json.dumps({"argv": [sys.executable, str(script)], "timeout_seconds": 60}),
        encoding="utf-8",
    )
    runner = CliRunner()
    created = runner.invoke(app, ["roleplay", "init", "--scenario", "evaluation_first_v1"])
    assert created.exit_code == 0

    first = runner.invoke(app, ["roleplay", "round", "--gemini-config", str(config)])
    assert first.exit_code == 0, first.stdout
    assert json.loads(first.stdout)["generation_status"] == "passed"
    decision = tmp_path / "d1.json"
    decision.write_text(json.dumps({
        "action": "revise", "words": "改一下，先讲评测。", "reason_category": "copy",
        "note": "开头先讲评测，不要客套", "revised_text": "您好，我搭过问答评测体系。",
        "triggered_preferences": ["P_EVAL_FIRST"],
    }, ensure_ascii=False), encoding="utf-8")
    decided = runner.invoke(app, ["roleplay", "decide", "1", str(decision)])
    assert decided.exit_code == 0, decided.stdout

    second = runner.invoke(app, ["roleplay", "round", "--gemini-config", str(config)])
    assert second.exit_code == 0, second.stdout
    assert json.loads(second.stdout)["selected_rules"]
    report = json.loads(runner.invoke(app, ["roleplay", "report"]).stdout)
    failed = [c["check_id"] for c in report["checks"] if not c["passed"]]
    assert failed == [] and report["memory_rules"]
