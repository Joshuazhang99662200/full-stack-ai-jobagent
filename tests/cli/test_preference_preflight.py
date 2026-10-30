import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from jobagent.cli.greetings import greetings_app
from jobagent.cli.jobs import jobs_app
from jobagent.errors import UserInterventionRequiredError
from jobagent.outreach.generation import content_digest
from jobagent.schemas.greeting import GreetingRequest
from jobagent.schemas.preference_memory import PreferenceMemory, PreferenceRule, PreferenceSelection
from jobagent.storage.database import Database

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def memory():
    rules = [
        PreferenceRule(rule_id="JOBS", category="jobs", scope="general", condition="All searches",
                       text="Prefer enterprise Agent products", source_event_ids=["EVENT_A"],
                       updated_at=NOW),
        PreferenceRule(rule_id="FINANCE", category="greetings", scope="role",
                       condition="Financial roles", text="Explain investment product experience",
                       source_event_ids=["EVENT_A"], updated_at=NOW),
        PreferenceRule(rule_id="DOCUMENTS", category="greetings", scope="role",
                       condition="Document roles", text="Explain report generation experience",
                       source_event_ids=["EVENT_A"], updated_at=NOW),
    ]
    return PreferenceMemory(candidate_id="CAND_TEST", version="PMEM_TEST",
                            rules=rules, consumed_event_ids=["EVENT_A"], updated_at=NOW)


def request(job_id=None):
    raw = "Build financial agents." if job_id == "JOB_FIN" else "Build document agents."
    job = {"job_id": job_id or "JOB_DOC", "title": "Product Manager",
           "company": "Synthetic Labs", "platform": "manual",
           "url": "https://jobs.example.test/role", "jd_raw": raw}
    return GreetingRequest.model_validate({
        "candidate_id": "CAND_TEST", "display_name": "Alex",
        "policy_digest": content_digest("synthetic policy"),
        "mode": "targeted" if job_id else "default", "job": job if job_id else None,
        "interests": [{"job": job, "selection_id": "OAPPROVAL_TEST"}],
        "evidence": [{"id": "EVID_TEST", "type": "project", "statement": "Built agents.",
                      "confidence": "explicit", "user_confirmed": True,
                      "source": {"type": "interview", "reference": "CHAT_TEST"}}],
    })


def fixture(tmp_path, monkeypatch, *, enabled=True):
    monkeypatch.chdir(tmp_path)
    private = tmp_path / "candidate" / "private"
    private.mkdir(parents=True)
    db = private / "db.sqlite3"
    Database(db).migrate()
    config = private / "settings.json"
    payload = {"candidate_id": "CAND_TEST", "display_name": "Alex"}
    if enabled:
        payload["memory_path"] = str(private / "preference-memory.md")
    config.write_text(json.dumps(payload), encoding="utf-8")
    filters = private / "filters.json"
    filters.write_text(json.dumps({"candidate_id": "CAND_TEST",
                                  "preferred_search_terms": ["Base Agent PM"]}))
    events = []

    def runner(*args, **kwargs):
        events.append(("runner", kwargs["timeout_seconds"]))
        return object()

    def refresh(database, path, candidate_id, provider, **kwargs):
        events.append(("refresh", candidate_id, str(path)))
        return memory()

    class Learner:
        def __init__(self, provider):
            pass

        def select(self, current, *, task, job_id, context):
            events.append(("select", task, job_id, context))
            if task == "search":
                rules = [rule for rule in current.rules if rule.category == "jobs"]
            else:
                rule_id = "FINANCE" if "financial" in context else "DOCUMENTS"
                rules = [rule for rule in current.rules if rule.rule_id == rule_id]
            return PreferenceSelection(
                memory_version=current.version, memory_digest=content_digest(current.model_dump(
                    mode="json")), rules=rules,
                search_queries=["Enterprise Agent PM"] if task == "search" else [],
            )

    class GreetingProvider:
        def generate(self, *, prompt_id, context, output_type):
            events.append((prompt_id, context))
            if "draft" in prompt_id:
                return output_type.model_validate({
                    "input_digest": context["input_digest"],
                    "text": "Hello, I built agents. Can we talk?", "angle": "Agent work",
                    "claims": [{"text": "I built agents", "evidence_ids": ["EVID_TEST"]}],
                    "jd_spans": [context["request"]["job"]["jd_raw"]]
                    if context["request"]["job"] else [],
                })
            return output_type.model_validate({
                "input_digest": context["input_digest"],
                "draft_digest": context["draft_digest"],
                "claims": [{"text": "I built agents", "verdict": "supported",
                            "reason": "Supported synthetic fact"}],
                "full_text_supported": True, "no_missing_claims": True,
                "target_relevant": True, "style_ok": True, "conflicts_resolved": True,
            })

    for module in ["jobagent.cli.greetings", "jobagent.cli.jobs"]:
        monkeypatch.setattr(module + ".CodexTextRunner", runner, raising=False)
        monkeypatch.setattr(module + "._find_executable", lambda _: "codex.exe", raising=False)
        monkeypatch.setattr(module + ".CodexPreferenceProvider", lambda _: object(), raising=False)
        monkeypatch.setattr(module + ".refresh_preference_memory", refresh, raising=False)
        monkeypatch.setattr(module + ".PreferenceLearner", Learner, raising=False)
    monkeypatch.setattr("jobagent.cli.greetings.load_greeting_request",
                        lambda *args, **kwargs: request(kwargs.get("job_id")))
    monkeypatch.setattr("jobagent.cli.greetings.CodexGreetingProvider",
                        lambda _: GreetingProvider())
    return config, db, filters, events


def greet(config, db, output, job_id=None):
    args = ["--candidate", "CAND_TEST", "--settings", str(config),
            "--database", str(db), "--output", str(output)]
    if job_id:
        args += ["--job", job_id]
    return CliRunner().invoke(greetings_app, args)


def search(config, db, filters, *extra, enabled=True, candidate="CAND_TEST"):
    args = ["search-plan", "--filter-context", str(filters), "--site", "liepin",
            "--candidate", candidate, "--database", str(db)]
    if enabled:
        args += ["--memory-settings", str(config)]
    return CliRunner().invoke(jobs_app, [*args, *extra])


def test_greeting_refresh_and_selection_happen_before_generation_and_share_snapshot(
    tmp_path, monkeypatch,
):
    config, db, _, events = fixture(tmp_path, monkeypatch)
    output = config.parent / "generated"
    result = greet(config, db, output, "JOB_FIN")
    assert result.exit_code == 0, result.stdout
    assert [event[0] for event in events] == [
        "runner", "refresh", "select", "greeting.ai.draft.v1", "greeting.ai.review.v1",
    ]
    selected = events[3][1]["request"]["preference_memory"]
    assert selected == events[4][1]["request"]["preference_memory"]
    assert [rule["rule_id"] for rule in selected["rules"]] == ["FINANCE"]
    assert "Build financial agents." in events[2][3]
    snapshot = json.loads((output / "request.json").read_text(encoding="utf-8"))
    assert snapshot["preference_memory"] == selected
    assert json.loads(result.stdout)["memory_version"] == "PMEM_TEST"


def test_two_jds_select_different_rules_and_default_explains_historical_direction(
    tmp_path, monkeypatch,
):
    config, db, _, events = fixture(tmp_path, monkeypatch)
    for job_id in ["JOB_FIN", "JOB_DOC", None]:
        result = greet(config, db, config.parent / (job_id or "default"), job_id)
        assert result.exit_code == 0, result.stdout
    drafts = [event[1]["request"]["preference_memory"] for event in events
              if event[0] == "greeting.ai.draft.v1"]
    assert [[rule["rule_id"] for rule in selected["rules"]] for selected in drafts[:2]] == [
        ["FINANCE"], ["DOCUMENTS"],
    ]
    selections = [event for event in events if event[0] == "select"]
    assert selections[-1][2] is None
    assert "default" in selections[-1][3].lower() or "通用" in selections[-1][3]
    assert "document" in selections[-1][3].lower()


def test_search_consumes_job_rules_and_produces_plan_without_remote_search(tmp_path, monkeypatch):
    config, db, filters, events = fixture(tmp_path, monkeypatch)
    result = search(config, db, filters)
    assert result.exit_code == 0, result.stdout
    assert [event[0] for event in events] == ["runner", "refresh", "select"]
    assert events[-1][1] == "search" and events[-1][2] is None
    assert "Base Agent PM" in events[-1][3] and "liepin" in events[-1][3]
    data = json.loads(result.stdout)
    assert data["memory_version"] == "PMEM_TEST"
    assert data["plans"]["liepin"]["chosen"][0]["term"] == "Enterprise Agent PM"
    assert [rule["category"] for rule in data["selections"]["liepin"]["rules"]] == ["jobs"]


def test_legacy_calls_do_not_refresh_select_or_add_model_calls(tmp_path, monkeypatch):
    config, db, filters, events = fixture(tmp_path, monkeypatch, enabled=False)
    result = greet(config, db, config.parent / "legacy")
    assert result.exit_code == 0, result.stdout
    assert not any(event[0] in {"refresh", "select"} for event in events)
    before_search = len(events)
    result = search(config, db, filters, enabled=False)
    assert result.exit_code == 0, result.stdout
    assert len(events) == before_search
    assert json.loads(result.stdout)["liepin"]["chosen"][0]["term"] == "Base Agent PM"


@pytest.mark.parametrize("kind", ["candidate", "public_memory", "public_settings"])
def test_memory_candidate_and_private_path_fail_before_model_calls(tmp_path, monkeypatch, kind):
    config, db, filters, events = fixture(tmp_path, monkeypatch)
    payload = json.loads(config.read_text())
    if kind == "candidate":
        payload["candidate_id"] = "CAND_OTHER"
    elif kind == "public_memory":
        payload["memory_path"] = str(tmp_path / "public-memory.md")
    else:
        config = tmp_path / "public-settings.json"
    config.write_text(json.dumps(payload))
    result = search(config, db, filters)
    assert result.exit_code == 1 and "CONTRACT_VALIDATION_ERROR" in result.stdout
    assert not events
    events.clear()
    result = greet(config, db, config.parent / "out")
    assert result.exit_code == 1 and "CONTRACT_VALIDATION_ERROR" in result.stdout
    assert not events


def test_search_requires_explicit_candidate_for_memory_settings(tmp_path, monkeypatch):
    config, db, filters, events = fixture(tmp_path, monkeypatch)
    result = CliRunner().invoke(jobs_app, [
        "search-plan", "--filter-context", str(filters), "--database", str(db),
        "--memory-settings", str(config),
    ])
    assert result.exit_code == 1 and "CONTRACT_VALIDATION_ERROR" in result.stdout
    assert not events


def test_refresh_failure_stops_generation_without_exporting_unlearned_request(
    tmp_path, monkeypatch,
):
    config, db, _, events = fixture(tmp_path, monkeypatch)

    def unavailable(*args, **kwargs):
        raise UserInterventionRequiredError("Preference summary unavailable")

    monkeypatch.setattr("jobagent.cli.greetings.refresh_preference_memory", unavailable)
    output = config.parent / "not-generated"
    result = greet(config, db, output, "JOB_FIN")
    assert result.exit_code == 1 and "USER_INTERVENTION_REQUIRED" in result.stdout
    assert [event[0] for event in events] == ["runner"]
    assert not output.exists()


def test_search_refreshes_once_and_selects_for_each_source(tmp_path, monkeypatch):
    config, db, filters, events = fixture(tmp_path, monkeypatch)
    result = search(config, db, filters, "--site", "zhaopin")
    assert result.exit_code == 0, result.stdout
    assert [event[0] for event in events] == ["runner", "refresh", "select", "select"]
    selections = [event for event in events if event[0] == "select"]
    assert "liepin" in selections[0][3] and "zhaopin" in selections[1][3]
    assert set(json.loads(result.stdout)["plans"]) == {"liepin", "zhaopin"}


def test_search_preserves_base_queries_when_memory_selects_no_replacement(tmp_path, monkeypatch):
    config, db, filters, _ = fixture(tmp_path, monkeypatch)

    class EmptySelection:
        def __init__(self, provider):
            pass

        def select(self, current, **kwargs):
            return PreferenceSelection(
                memory_version=current.version,
                memory_digest=content_digest(current.model_dump(mode="json")),
            )

    monkeypatch.setattr("jobagent.cli.jobs.PreferenceLearner", EmptySelection)
    result = search(config, db, filters)
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["plans"]["liepin"]["chosen"][0]["term"] == "Base Agent PM"
    assert data["selections"]["liepin"]["search_queries"] == []
