"""End to end: owner feedback -> preference memory -> greeting -> ledger evidence of use.

Synthetic data only. Model calls are stubbed; every stage still runs through the
real contracts, storage and checks.
"""

from datetime import timedelta

from jobagent.bridge.greeting_context import load_greeting_request
from jobagent.bridge.preference_memory import refresh_preference_memory
from jobagent.memory.usage import summarize_memory_usage
from jobagent.outreach.generation import GreetingGenerator
from jobagent.outreach.preference_memory import PreferenceLearner
from jobagent.outreach.service import OutreachService
from jobagent.schemas.greeting import GreetingRequest
from jobagent.schemas.preference_memory import PreferenceRule
from jobagent.schemas.sourcing_feedback import OutreachFeedbackRequest
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_greeting_context import NOW, populated, settings

REVISED = "Hello, I evaluate grounded research agents. Shall we talk?"
DRAFT = "Hello, I built research agents and evaluate grounded answers. Can we talk?"


class Model:
    """Stands in for every model call; records which prompts ran."""

    def __init__(self, job_id: str, event_id: str) -> None:
        self.job_id, self.event_id, self.prompts = job_id, event_id, []

    def generate(self, *, prompt_id, context, output_type):
        self.prompts.append(prompt_id)
        if prompt_id == "preference.memory.summarize.v1":
            assert [e["event_id"] for e in context["events"]] == [self.event_id]
            return output_type(input_digest=context["input_digest"], rules=[PreferenceRule(
                rule_id="RULE_EVAL_FIRST", category="greetings", scope="job",
                condition="This JD", job_id=self.job_id,
                text="Lead with evaluation of grounded answers.",
                source_event_ids=[self.event_id], updated_at=NOW,
            )])
        if prompt_id == "preference.memory.select.v1":
            return output_type(
                input_digest=context["input_digest"], selected_rule_ids=["RULE_EVAL_FIRST"]
            )
        if "draft" in prompt_id:
            assert [r["rule_id"] for r in context["request"]["preference_memory"]["rules"]] == [
                "RULE_EVAL_FIRST"
            ]
            return output_type(
                input_digest=context["input_digest"], text=DRAFT, angle="Evaluation first",
                claims=[{"text": "I built research agents", "evidence_ids": ["EVID_CURRENT"]}],
                jd_spans=["evaluate grounded model answers"],
            )
        return output_type(
            input_digest=context["input_digest"], draft_digest=context["draft_digest"],
            claims=[{"text": c["text"], "verdict": "supported", "reason": "Matches evidence"}
                    for c in context["draft"]["claims"]],
            full_text_supported=True, no_missing_claims=True, target_relevant=True,
            style_ok=True, conflicts_resolved=True,
        )


def test_owner_feedback_reaches_a_greeting_and_its_use_is_provable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database, job_id = populated(tmp_path, approved=False)
    db = Database(database)
    outreach = SqliteOutreachRepository(db)
    with db.connect() as connection:
        ask_id = connection.execute("SELECT ask_id FROM outreach_asks").fetchone()[0]

    # 1. The person rewrites item 1 instead of approving it; the host records it.
    receipt = SqliteFeedbackRepository(db).record_outreach_feedback(OutreachFeedbackRequest(
        batch_id="OBATCH_FIXTURE", ask_id=ask_id, candidate_id="CAND_TEST",
        actor_id="OWNER_SYNTHETIC", attestation="第 1 条改成我写的这句。",
        occurred_at=NOW + timedelta(minutes=1),
        items=[{"number": 1, "action": "revise", "revised_text": REVISED,
                "reason_category": "copy"}],
    ))
    model = Model(job_id, receipt.items[0].event_id)

    # 2. Preference memory consumes exactly that event into a cited rule.
    memory_path = tmp_path / "candidate" / "private" / "preference-memory.md"
    memory = refresh_preference_memory(database, memory_path, "CAND_TEST", model, now=NOW)
    assert memory.consumed_event_ids == [receipt.items[0].event_id]
    assert memory.rules[0].source_event_ids == [receipt.items[0].event_id]

    # 3. The targeted greeting selects the rule and is generated with it.
    request = load_greeting_request(database, settings(), job_id=job_id)
    assert any(REVISED in note for note in request.feedback)
    selection = PreferenceLearner(model).select(
        memory, task="greeting", job_id=job_id, context=request.job.jd_raw if request.job else "",
    )
    request = GreetingRequest.model_validate(
        {**request.model_dump(), "preference_memory": selection.model_dump()}
    )
    report = GreetingGenerator(model).generate(request)
    assert report.status == "passed" and report.outreach_draft is not None

    # 4. The draft enters a new list, is asked and approved by the person.
    job = SqliteJobRepository(db).get_job(job_id)
    assert job is not None
    service = OutreachService()
    built = service.build_batch(
        [report.outreach_draft], jobs={job_id: job}, already_contacted=set(),
        confirmed_evidence_ids={"EVID_CURRENT"}, batch_id="OBATCH_MEMORY", created_at=NOW,
    )
    assert built.batch is not None, built.rejected
    outreach.save_batch(built.batch)
    ask = service.ask(built.batch, asked_at=NOW)
    outreach.save_ask(ask)
    outreach.save_approval(service.approve(
        built.batch, ask=ask, numbers=[1], attestation="可以发", approved_at=NOW,
    ))

    # 5. The ledger proves which memory version and rule reached the approved item.
    batches = outreach.list_batches()
    usage = summarize_memory_usage(
        "CAND_TEST", batches=batches,
        approvals={b.batch_id: a for b in batches if (a := outreach.get_approval(b.batch_id))},
        audits=outreach.list_audits(),
    )
    assert [(v.memory_version, v.drafted, v.approved) for v in usage.memory_versions] == [
        (memory.version, 1, 1)
    ]
    assert [(r.rule_id, r.drafted, r.approved, r.sent) for r in usage.rules] == [
        ("RULE_EVAL_FIRST", 1, 1, 0)
    ]
    # The first, feedback-only list carries no provenance and is not credited to memory.
    assert usage.unattributed.drafted == 1 and usage.unattributed.approved == 0
