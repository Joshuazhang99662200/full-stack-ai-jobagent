"""Synthetic role-play evaluation of the memory loop.

A simulated owner (for example a local Claude session playing a synthetic persona)
judges greetings that a local model (for example Gemini) drafts and reviews. The
model never sees the persona or its hidden preferences; it can only learn them
through the recorded feedback and preference memory, which is exactly what this
harness measures. Everything runs in an isolated private workspace under
`.jobagent/roleplay` of the current directory, with a synthetic candidate and
synthetic postings. Nothing here sends anything or may be used for real outreach.

Every step goes through the production services: evidence is confirmed through
CandidateEvidenceService, approvals through OutreachService.approve on an asked
list, feedback through the outreach feedback writer, and greetings through the
real generator and independent review.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from jobagent.bridge.greeting_context import load_greeting_request
from jobagent.bridge.greeting_generation import CodexGreetingProvider
from jobagent.bridge.preference_memory import (
    MarkdownPreferenceStore,
    load_preference_events,
    refresh_preference_memory,
)
from jobagent.bridge.preference_reasoning import CodexPreferenceProvider
from jobagent.candidate.evidence import CandidateEvidenceService
from jobagent.capabilities import TextRunner
from jobagent.errors import ContractValidationError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.memory.usage import summarize_memory_usage
from jobagent.outreach.generation import GreetingGenerator
from jobagent.outreach.preference_memory import PreferenceLearner
from jobagent.outreach.service import OutreachService
from jobagent.schemas.candidate import CandidateProfile, EvidenceItem
from jobagent.schemas.greeting import GreetingRequest, GreetingSettings
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.roleplay import (
    PreferenceCapture,
    RoleplayCheck,
    RoleplayDecision,
    RoleplayReport,
    RoleplayRound,
    RoleplayScenario,
)
from jobagent.schemas.sourcing_feedback import OutreachFeedbackItem, OutreachFeedbackRequest
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

OWNER = "ROLEPLAY_SIMULATED_OWNER"


@dataclass(frozen=True)
class RoleplayPaths:
    root: Path

    @classmethod
    def here(cls) -> "RoleplayPaths":
        return cls(Path.cwd().resolve() / ".jobagent" / "roleplay")

    @property
    def database(self) -> Path:
        return self.root / "jobagent.sqlite3"

    @property
    def memory(self) -> Path:
        return self.root / "preference-memory.md"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def scenario(self) -> Path:
        return self.root / "scenario.json"

    @property
    def rounds(self) -> Path:
        return self.root / "rounds"


def load_scenario(name: str) -> RoleplayScenario:
    resource = resources.files("jobagent.evals.scenarios").joinpath(f"{name}.json")
    if not resource.is_file():
        raise ContractValidationError("Unknown role-play scenario.", details={"scenario": name})
    return RoleplayScenario.model_validate_json(resource.read_text(encoding="utf-8"))


def _read_state(paths: RoleplayPaths) -> dict[str, Any]:
    if not paths.state.is_file():
        raise ContractValidationError("No role-play workspace here; run `roleplay init` first.")
    return dict(json.loads(paths.state.read_text(encoding="utf-8")))


def _write_state(paths: RoleplayPaths, state: dict[str, Any]) -> None:
    temporary = paths.state.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(paths.state)


def _scenario(paths: RoleplayPaths) -> RoleplayScenario:
    return RoleplayScenario.model_validate_json(paths.scenario.read_text(encoding="utf-8"))


def init_workspace(
    paths: RoleplayPaths, scenario: RoleplayScenario, *, now: datetime
) -> dict[str, object]:
    if paths.root.exists():
        raise ContractValidationError("Use a fresh directory; this role-play workspace exists.")
    paths.rounds.mkdir(parents=True)
    paths.scenario.write_text(scenario.model_dump_json(indent=2), encoding="utf-8")
    db = Database(paths.database)
    db.migrate()
    candidates = SqliteCandidateRepository(db)
    candidates.save_profile(
        CandidateProfile(id=scenario.candidate_id, full_name=scenario.display_name)
    )
    evidence = CandidateEvidenceService(candidates)
    for item in scenario.evidence:
        evidence.add_draft(scenario.candidate_id, EvidenceItem.model_validate({
            "id": item.evidence_id, "type": "project", "statement": item.statement,
            "skills": item.skills, "confidence": "explicit",
            "source": {"type": "interview", "reference": "ROLEPLAY_SYNTHETIC_PERSONA"},
        }))
        # The synthetic persona's scenario is its own confirmed record.
        evidence.confirm(scenario.candidate_id, item.evidence_id)
    jobs = SqliteJobRepository(db)
    job_ids = []
    for posting in scenario.jobs:
        job = JobNormalizer().normalize(SourceJobRecord.model_validate({
            "source": "boss", "source_job_id": posting.source_job_id,
            "company": posting.company, "title": posting.title,
            "location": posting.location, "jd_raw": posting.jd_raw, "url": posting.url,
            "collected_at": now,
        }))
        jobs.save_job(job)
        job_ids.append(job.id)
    state = {"scenario_id": scenario.scenario_id, "job_ids": job_ids, "rounds": []}
    _write_state(paths, state)
    return {"workspace": str(paths.root), "jobs": len(job_ids), "synthetic_only": True}


def _settings(scenario: RoleplayScenario, paths: RoleplayPaths) -> GreetingSettings:
    return GreetingSettings(
        candidate_id=scenario.candidate_id, display_name=scenario.display_name,
        memory_path=str(paths.memory),
    )


def run_round(paths: RoleplayPaths, runner: TextRunner, *, now: datetime) -> RoleplayRound:
    state = _read_state(paths)
    scenario = _scenario(paths)
    rounds = state["rounds"]
    if rounds and rounds[-1]["status"] == "passed" and rounds[-1]["decision"] is None:
        raise ContractValidationError(
            "Decide the open round first.", details={"round": rounds[-1]["round"]}
        )
    number = len(rounds) + 1
    job_id = state["job_ids"][(number - 1) % len(state["job_ids"])]
    db = Database(paths.database)
    preference = CodexPreferenceProvider(runner)
    memory = refresh_preference_memory(
        paths.database, paths.memory, scenario.candidate_id, preference, now=now
    )
    events = load_preference_events(paths.database, scenario.candidate_id)
    unconsumed = len({e.event_id for e in events} - set(memory.consumed_event_ids))
    job = SqliteJobRepository(db).get_job(job_id)
    assert job is not None
    selection = PreferenceLearner(preference).select(
        memory, task="greeting", job_id=job_id, context=job.jd_raw
    )
    request = load_greeting_request(paths.database, _settings(scenario, paths), job_id=job_id)
    request = GreetingRequest.model_validate(
        {**request.model_dump(), "preference_memory": selection.model_dump()}
    )
    report = GreetingGenerator(CodexGreetingProvider(runner)).generate(request)
    (paths.rounds / f"R{number:04d}.report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    view = RoleplayRound(
        round_number=number, job_id=job_id, title=job.title, company=job.company,
        jd_raw=job.jd_raw, generation_status=report.status, memory_version=memory.version,
        memory_rule_count=len(memory.rules),
        selected_rules=[rule.rule_id for rule in selection.rules],
        selected_rule_texts=[rule.text for rule in selection.rules],
        unconsumed_events_before_generation=unconsumed, started_at=now,
    )
    if report.status == "passed" and report.outreach_draft is not None:
        service, store = OutreachService(), SqliteOutreachRepository(db)
        owned = {
            e.id for e in SqliteCandidateRepository(db).list_evidence(scenario.candidate_id)
            if e.user_confirmed
        }
        built = service.build_batch(
            [report.outreach_draft], jobs={job_id: job}, already_contacted=set(),
            confirmed_evidence_ids=owned, batch_id=f"OBATCH_RP_{number:04d}", created_at=now,
        )
        if built.batch is None:
            view.generation_status = "rejected"
        else:
            store.save_batch(built.batch)
            ask = service.ask(built.batch, asked_at=now)
            store.save_ask(ask)
            view.greeting = built.batch.items[0].text
            view.batch_id, view.ask_id = built.batch.batch_id, ask.ask_id
    (paths.rounds / f"R{number:04d}.json").write_text(
        view.model_dump_json(indent=2), encoding="utf-8"
    )
    rounds.append({
        "round": number, "status": view.generation_status, "decision": None,
        "triggered": [], "batch_id": view.batch_id, "ask_id": view.ask_id,
    })
    _write_state(paths, state)
    return view


def decide_round(
    paths: RoleplayPaths, number: int, decision: RoleplayDecision, *, now: datetime
) -> dict[str, object]:
    state = _read_state(paths)
    scenario = _scenario(paths)
    rounds = state["rounds"]
    if not rounds or rounds[-1]["round"] != number:
        raise ContractValidationError("Only the latest round can be decided.")
    current = rounds[-1]
    if current["status"] != "passed" or current["decision"] is not None:
        raise ContractValidationError("This round has no open greeting to decide.")
    unknown = set(decision.triggered_preferences) - {
        p.preference_id for p in scenario.hidden_preferences
    }
    if unknown:
        raise ContractValidationError(
            "Unknown hidden preference.", details={"ids": sorted(unknown)}
        )
    db = Database(paths.database)
    store = SqliteOutreachRepository(db)
    batch, ask = store.get_batch(current["batch_id"]), store.get_ask(current["ask_id"])
    assert batch is not None and ask is not None
    if decision.action == "approve":
        store.save_approval(OutreachService().approve(
            batch, ask=ask, numbers=[1], attestation=decision.words, approved_at=now
        ))
    receipt = SqliteFeedbackRepository(db).record_outreach_feedback(OutreachFeedbackRequest(
        batch_id=batch.batch_id, ask_id=ask.ask_id, candidate_id=scenario.candidate_id,
        actor_id=OWNER, attestation=decision.words, occurred_at=now,
        query_strategy_version=f"roleplay:{scenario.scenario_id}",
        items=[OutreachFeedbackItem(
            number=1, action=decision.action, reason_category=decision.reason_category,
            free_text=decision.note, revised_text=decision.revised_text,
        )],
    ))
    current["decision"] = decision.action
    current["triggered"] = decision.triggered_preferences
    _write_state(paths, state)
    return {"round": number, "event_id": receipt.items[0].event_id, "grants_send": False}


def _rate(rounds: list[dict[str, Any]]) -> float | None:
    return sum(r["decision"] == "approve" for r in rounds) / len(rounds) if rounds else None


def build_report(paths: RoleplayPaths) -> RoleplayReport:
    state = _read_state(paths)
    scenario = _scenario(paths)
    db = Database(paths.database)
    store = SqliteOutreachRepository(db)
    memory = MarkdownPreferenceStore(paths.memory, scenario.candidate_id).load()
    events = load_preference_events(paths.database, scenario.candidate_id)
    event_ids = {event.event_id for event in events}
    rounds = state["rounds"]
    decided = [r for r in rounds if r["decision"] is not None]
    views = [
        RoleplayRound.model_validate_json(
            (paths.rounds / f"R{r['round']:04d}.json").read_text(encoding="utf-8")
        )
        for r in rounds
    ]
    batches = store.list_batches()
    approvals = {b.batch_id: a for b in batches if (a := store.get_approval(b.batch_id))}
    provenance_ok = True
    for view in views:
        if view.batch_id is None:
            continue
        batch = store.get_batch(view.batch_id)
        binding = batch.items[0].source_binding if batch else None
        generation = binding.generation if binding else None
        if (generation is None or generation.memory_version != view.memory_version
                or sorted(generation.preference_rule_ids) != sorted(view.selected_rules)):
            provenance_ok = False
    checks = [
        RoleplayCheck(
            check_id="decisions_recorded_as_bound_feedback",
            passed=len(event_ids) == len(decided),
            detail=f"{len(event_ids)} bound events for {len(decided)} decisions",
        ),
        RoleplayCheck(
            check_id="memory_consumed_feedback_before_each_generation",
            passed=all(v.unconsumed_events_before_generation == 0 for v in views),
            detail="unconsumed per round: "
            + ",".join(str(v.unconsumed_events_before_generation) for v in views),
        ),
        RoleplayCheck(
            check_id="rules_cite_only_recorded_events",
            passed=all(set(rule.source_event_ids) <= event_ids for rule in memory.rules),
            detail=f"{len(memory.rules)} rules",
        ),
        RoleplayCheck(
            check_id="each_draft_records_its_memory_provenance",
            passed=provenance_ok, detail="source binding generation vs round record",
        ),
        RoleplayCheck(
            check_id="approvals_only_for_approve_decisions",
            passed=len(approvals) == sum(r["decision"] == "approve" for r in rounds),
            detail=f"{len(approvals)} approvals",
        ),
        RoleplayCheck(
            check_id="selected_rules_reach_the_ledger",
            passed=bool(views) and sum(
                rule.drafted for rule in summarize_memory_usage(
                    scenario.candidate_id, batches=batches, approvals=approvals,
                    audits=store.list_audits(),
                ).rules
            ) == sum(len(v.selected_rules) for v in views if v.batch_id),
            detail="memory usage rule counts vs selections",
        ),
    ]
    preferences = []
    for preference in scenario.hidden_preferences:
        matching = [
            rule.text for rule in memory.rules
            if rule.category == preference.category
            and any(word.casefold() in rule.text.casefold() for word in preference.rule_keywords)
        ]
        preferences.append(PreferenceCapture(
            preference_id=preference.preference_id,
            triggered_rounds=[
                r["round"] for r in rounds if preference.preference_id in r["triggered"]
            ],
            captured=bool(matching), matching_rules=matching,
        ))
    half = len(decided) // 2
    actions: dict[str, int] = {}
    for r in decided:
        actions[r["decision"]] = actions.get(r["decision"], 0) + 1
    actions["generation_rejected"] = sum(r["status"] == "rejected" for r in rounds)
    return RoleplayReport(
        scenario_id=scenario.scenario_id, rounds=len(rounds), decided=len(decided),
        actions=actions, first_half_acceptance=_rate(decided[:half]),
        second_half_acceptance=_rate(decided[half:]), checks=checks, preferences=preferences,
        memory_version=memory.version,
        memory_rules=[f"[{rule.category}] {rule.text}" for rule in memory.rules],
    )
