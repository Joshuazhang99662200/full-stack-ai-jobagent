"""Which memory and rules shaped a greeting must survive into the outreach ledger."""

from datetime import UTC, datetime

from jobagent.digest import canonical_digest
from jobagent.memory.usage import summarize_memory_usage
from jobagent.outreach.generation import GreetingGenerator
from jobagent.outreach.service import OutreachService, _item_digest, _job_content
from jobagent.schemas.greeting import GreetingRequest
from jobagent.schemas.outreach import (
    OutreachAudit,
    OutreachDraft,
    OutreachResult,
    OutreachSourceBinding,
)
from tests.outreach.test_generation import Provider, request
from tests.outreach.test_service import JOBS

NOW = datetime(2026, 11, 1, tzinfo=UTC)
RULE = {
    "rule_id": "PREF_EVAL_FIRST", "category": "greetings", "scope": "general",
    "condition": "Any role", "text": "Lead with evaluation work.",
    "source_event_ids": ["OFB_SYNTHETIC"], "updated_at": NOW.isoformat(),
}


def with_memory(base: GreetingRequest) -> GreetingRequest:
    return GreetingRequest.model_validate({
        **base.model_dump(),
        "preference_memory": {
            "memory_version": "PMEM_SYNTHETIC_V2",
            "memory_digest": canonical_digest("memory-v2"),
            "rules": [RULE],
        },
        "dynamic_rules_version": canonical_digest("rules-v7"),
    })


def test_targeted_draft_records_the_memory_rules_and_input_it_was_generated_from():
    report = GreetingGenerator(Provider()).generate(with_memory(request(targeted=True)))

    assert report.outreach_draft is not None
    binding = report.outreach_draft.source_binding
    assert binding is not None and binding.generation is not None
    assert binding.generation.input_digest == report.input_digest
    assert binding.generation.memory_version == "PMEM_SYNTHETIC_V2"
    assert binding.generation.memory_digest == canonical_digest("memory-v2")
    assert binding.generation.preference_rule_ids == ["PREF_EVAL_FIRST"]
    assert binding.generation.dynamic_rules_version == canonical_digest("rules-v7")


def test_generation_without_memory_records_that_none_was_used():
    report = GreetingGenerator(Provider()).generate(request(targeted=True))

    assert report.outreach_draft is not None and report.outreach_draft.source_binding
    generation = report.outreach_draft.source_binding.generation
    assert generation is not None
    assert generation.memory_version is None and generation.preference_rule_ids == []


def test_bindings_without_generation_keep_their_stored_item_digest():
    job = next(iter(JOBS.values()))
    binding = OutreachSourceBinding(
        candidate_id="CAND_TEST", evidence_ids=["EVID_A"],
        evidence_digest=canonical_digest("e"), job_digest=canonical_digest("j"),
        text_digest=canonical_digest("t"), policy_digest=canonical_digest("p"),
    )
    draft = OutreachDraft(job_id=job.id, platform=job.source, text="Hello.", source_binding=binding)
    legacy = {
        key: value for key, value in binding.model_dump(mode="json").items()
        if key != "generation"
    }
    expected = canonical_digest({
        "job": _job_content(job), "platform": job.source, "text": "Hello.",
        "source_binding": legacy,
    })
    assert _item_digest(job, draft) == expected


def test_usage_counts_drafted_approved_and_sent_items_per_memory_version_and_rule():
    report = GreetingGenerator(Provider()).generate(with_memory(request(targeted=True)))
    assert report.outreach_draft is not None
    job = next(iter(JOBS.values()))
    remembered = report.outreach_draft.model_copy(
        update={"job_id": job.id, "platform": job.source}
    )
    plain = OutreachDraft(job_id=list(JOBS)[1], platform=JOBS[list(JOBS)[1]].source,
                          text="Hello, a plain greeting.")
    service = OutreachService()
    built = service.build_batch(
        [remembered, plain], jobs=JOBS, already_contacted=set(),
        confirmed_evidence_ids={"EVID_REPORT"}, batch_id="OBATCH_USAGE", created_at=NOW,
    )
    batch = built.batch
    assert batch is not None, built.rejected
    ask = service.ask(batch, asked_at=NOW)
    approval = service.approve(
        batch, ask=ask, numbers=[1, 2], attestation="都可以", approved_at=NOW
    )
    sent = OutreachAudit(
        audit_id="OAUDIT_USAGE_1", batch_id=batch.batch_id, number=1, job_id=job.id,
        platform=job.source, item_digest=batch.items[0].item_digest,
        approval_id=approval.approval_id, approval_channel=approval.channel,
        result=OutreachResult.SENT, recorded_at=NOW,
    )

    usage = summarize_memory_usage(
        "CAND_TEST", batches=[batch], approvals={batch.batch_id: approval}, audits=[sent],
    )

    version = usage.memory_versions[0]
    assert (version.memory_version, version.drafted, version.approved, version.sent) == (
        "PMEM_SYNTHETIC_V2", 1, 1, 1,
    )
    rule = usage.rules[0]
    assert (rule.rule_id, rule.drafted, rule.approved, rule.sent) == ("PREF_EVAL_FIRST", 1, 1, 1)
    assert usage.unattributed.drafted == 1 and usage.unattributed.sent == 0
    assert usage.grants_approval is False


def test_cli_reports_ledger_items_without_provenance_as_unattributed(tmp_path):
    import json

    from typer.testing import CliRunner

    from jobagent.cli.app import app
    from tests.bridge.test_greeting_context import populated

    path, _ = populated(tmp_path, approved=True)
    result = CliRunner().invoke(
        app, ["memory", "usage", "--candidate", "CAND_TEST", "--database", str(path)]
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["memory_versions"] == [] and report["rules"] == []
    unattributed = report["unattributed"]
    assert (unattributed["drafted"], unattributed["approved"], unattributed["sent"]) == (1, 1, 0)
    assert report["evidence"] == "outreach_ledger"
