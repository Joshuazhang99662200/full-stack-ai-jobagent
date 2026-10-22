# ruff: noqa: RUF001  -- Chinese greetings carry full-width punctuation by design.
from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ApprovalRequiredError, StaleApprovalError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.outreach.service import OutreachService, contacted_job_ids
from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.outreach import OutreachAudit, OutreachDraft, OutreachPolicy, OutreachResult

GREETING = "您好，我现任 AI 产品负责人，主导初创公司多款 Agent 产品从 0 到 1 开发。方便聊聊吗？"
NOW = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)


def job(source: str, source_job_id: str) -> NormalizedJob:
    return JobNormalizer().normalize(
        SourceJobRecord(
            source=source,
            source_job_id=source_job_id,
            title="Agent 产品经理",
            company=f"公司{source_job_id}",
            location="上海",
            jd_raw="负责 Agent 产品的规划与落地,需要熟悉 Skill 与工作流设计。" * 2,
            url=f"https://example.com/{source_job_id}",
            collected_at=NOW,
        )
    )


JOBS = {item.id: item for item in (job("boss", "a"), job("boss", "b"), job("zhaopin", "c"))}
IDS = list(JOBS)


def build(drafts: list[OutreachDraft], **kwargs: object):  # type: ignore[no-untyped-def]
    return OutreachService().build_batch(
        drafts,
        jobs=JOBS,
        already_contacted=kwargs.get("already_contacted", set()),  # type: ignore[arg-type]
        confirmed_evidence_ids=kwargs.get("confirmed", set()),  # type: ignore[arg-type]
        batch_id="OBATCH_001",
        created_at=NOW,
        policy=kwargs.get("policy"),  # type: ignore[arg-type]
    )


def draft(index: int, text: str = GREETING, **overrides: object) -> OutreachDraft:
    job_id = IDS[index]
    values: dict[str, object] = {"job_id": job_id, "platform": JOBS[job_id].source, "text": text}
    values.update(overrides)
    return OutreachDraft(**values)  # type: ignore[arg-type]


def approved_batch(numbers: list[int], policy: OutreachPolicy | None = None):  # type: ignore[no-untyped-def]
    service = OutreachService()
    report = build([draft(0), draft(1), draft(2)], policy=policy)
    assert report.batch is not None
    ask = service.ask(report.batch, asked_at=NOW)
    approval = service.approve(
        report.batch, ask=ask, numbers=numbers, attestation="发 1-3", approved_at=NOW
    )
    return service, report.batch, approval


def audit(batch, number: int, result: OutreachResult, at: datetime) -> OutreachAudit:  # type: ignore[no-untyped-def]
    item = batch.items[number - 1]
    return OutreachAudit(
        audit_id=f"OAUDIT_{number}_{result.value.upper()}",
        batch_id=batch.batch_id,
        number=number,
        job_id=item.job_id,
        platform=item.platform,
        item_digest=item.item_digest,
        approval_id="OAPPROVAL_001",
        approval_channel=ApprovalChannel.AGENT_RELAY,
        result=result,
        recorded_at=at,
    )


def test_batch_lists_valid_drafts_and_rejects_the_rest_with_reasons() -> None:
    report = build(
        [
            draft(0),
            draft(1, text="专家修订率降到 26%。方便聊聊吗？"),
            draft(2, platform="boss"),
            draft(0),
            OutreachDraft(job_id="JOB_UNKNOWN", platform="boss", text=GREETING),
        ],
    )

    assert report.batch is not None
    assert [item.job_id for item in report.batch.items] == [IDS[0]]
    reasons = {rejection.index: rejection.reasons for rejection in report.rejected}
    assert "contains_number" in reasons[1] and "banned_phrase:修订率" in reasons[1]
    assert reasons[2] == ["platform_mismatch"]
    assert reasons[3] == ["duplicate_in_batch"]
    assert reasons[4] == ["job_not_stored"]


def test_already_contacted_jobs_and_unconfirmed_evidence_are_refused() -> None:
    report = build(
        [draft(0), draft(1, evidence_ids=["EVID_DRAFT"])],
        already_contacted={IDS[0]},
        confirmed=set(),
    )

    assert report.batch is None
    assert [rejection.reasons for rejection in report.rejected] == [
        ["already_contacted"],
        ["unconfirmed_evidence"],
    ]


def test_relayed_approval_must_answer_a_question_about_this_exact_batch() -> None:
    service = OutreachService()
    report = build([draft(0), draft(1)])
    assert report.batch is not None
    ask = service.ask(report.batch, asked_at=NOW)

    with pytest.raises(ApprovalRequiredError):
        service.approve(report.batch, ask=None, numbers=[1], attestation="发 1", approved_at=NOW)
    with pytest.raises(ApprovalRequiredError):
        service.approve(report.batch, ask=ask, numbers=[1], attestation=" ", approved_at=NOW)
    with pytest.raises(ApprovalRequiredError):
        service.approve(report.batch, ask=ask, numbers=[3], attestation="发 3", approved_at=NOW)
    changed = build([draft(0), draft(1, text=GREETING + "谢谢。")]).batch
    assert changed is not None
    with pytest.raises(ApprovalRequiredError):
        service.approve(changed, ask=ask, numbers=[1], attestation="发 1", approved_at=NOW)

    approval = service.approve(
        report.batch, ask=ask, numbers=[2, 1], attestation="发 1、2", approved_at=NOW
    )
    assert approval.approved_numbers == [1, 2]
    assert approval.channel is ApprovalChannel.AGENT_RELAY


def test_next_gives_approved_items_in_order_and_respects_the_interval() -> None:
    service, batch, approval = approved_batch([1, 2, 3])

    first = service.next_item(batch, approval, platform="boss", audits=[], lease_held=True, now=NOW)
    assert first.allowed and first.item is not None and first.item.number == 1

    sent = [audit(batch, 1, OutreachResult.SENT, NOW)]
    soon = service.next_item(
        batch,
        approval,
        platform="boss",
        audits=sent,
        lease_held=True,
        now=NOW + timedelta(seconds=10),
    )
    assert not soon.allowed and soon.reason == "too_soon" and soon.wait_seconds == 20

    later = service.next_item(
        batch,
        approval,
        platform="boss",
        audits=sent,
        lease_held=True,
        now=NOW + timedelta(minutes=3),
    )
    assert later.allowed and later.item is not None and later.item.number == 2


def test_next_refuses_without_lease_unapproved_items_and_stale_batches() -> None:
    service, batch, approval = approved_batch([1])

    no_lease = service.next_item(
        batch, approval, platform="boss", audits=[], lease_held=False, now=NOW
    )
    assert no_lease.reason == "lease_not_held"

    done = [audit(batch, 1, OutreachResult.SENT, NOW)]
    nothing = service.next_item(
        batch, approval, platform="boss", audits=done, lease_held=True, now=NOW + timedelta(hours=1)
    )
    assert nothing.reason == "nothing_left"

    stale = batch.model_copy(update={"batch_digest": "sha256:other"})
    with pytest.raises(StaleApprovalError):
        service.next_item(stale, approval, platform="boss", audits=[], lease_held=True, now=NOW)


def test_failure_or_risk_control_halts_the_platform_for_the_day() -> None:
    service, batch, approval = approved_batch([1, 2, 3])
    halted = [audit(batch, 1, OutreachResult.INTERVENTION, NOW)]

    same_day = service.next_item(
        batch,
        approval,
        platform="boss",
        audits=halted,
        lease_held=True,
        now=NOW + timedelta(hours=2),
    )
    assert same_day.reason == "platform_halted_today"

    other_platform = service.next_item(
        batch, approval, platform="zhaopin", audits=halted, lease_held=True, now=NOW
    )
    assert other_platform.allowed

    next_day = service.next_item(
        batch,
        approval,
        platform="boss",
        audits=halted,
        lease_held=True,
        now=NOW + timedelta(days=1),
    )
    assert next_day.allowed and next_day.item is not None and next_day.item.number == 2


def test_daily_cap_counts_every_send_on_the_platform_that_day() -> None:
    service, batch, approval = approved_batch([1, 2], OutreachPolicy(daily_cap_per_platform=1))
    sent_elsewhere = [
        audit(batch, 1, OutreachResult.SENT, NOW).model_copy(update={"batch_id": "OBATCH_OTHER"})
    ]

    capped = service.next_item(
        batch,
        approval,
        platform="boss",
        audits=sent_elsewhere,
        lease_held=True,
        now=NOW + timedelta(hours=1),
    )
    assert capped.reason == "daily_cap_reached"


def test_policy_limits_cannot_be_loosened() -> None:
    with pytest.raises(ValueError):
        OutreachPolicy(daily_cap_per_platform=51)
    with pytest.raises(ValueError):
        OutreachPolicy(min_seconds_between_sends=20)


def test_the_default_interval_between_sends_is_thirty_seconds() -> None:
    assert OutreachPolicy().min_seconds_between_sends == 30


def test_greetings_cascade_by_match_tier_and_weak_matches_are_not_drafted() -> None:
    drafts = [draft(0), draft(1), draft(2)]
    tiers = {IDS[0]: "possible_match", IDS[1]: "weak_match", IDS[2]: "strong_match"}

    report = OutreachService().build_batch(
        drafts,
        jobs=JOBS,
        already_contacted=set(),
        confirmed_evidence_ids=set(),
        batch_id="OBATCH_001",
        created_at=NOW,
        match_tiers=tiers,
    )

    assert report.batch is not None
    assert [(i.job_id, i.match_tier) for i in report.batch.items] == [
        (IDS[2], "strong_match"),
        (IDS[0], "possible_match"),
    ]
    assert [(r.index, r.reasons) for r in report.rejected] == [(1, ["weak_match"])]
    question = OutreachService().ask(report.batch, asked_at=NOW).question
    assert question.index("【强匹配】") < question.index("【可能匹配】")


def test_possible_matches_need_enough_preference_when_a_floor_is_set() -> None:
    drafts = [draft(0), draft(1), draft(2)]
    tiers = {IDS[0]: "possible_match", IDS[1]: "possible_match", IDS[2]: "strong_match"}

    report = OutreachService().build_batch(
        drafts,
        jobs=JOBS,
        already_contacted=set(),
        confirmed_evidence_ids=set(),
        batch_id="OBATCH_001",
        created_at=NOW,
        match_tiers=tiers,
        preferences={IDS[0]: 0.9, IDS[1]: 0.4, IDS[2]: 0.1},
        possible_match_min_preference=0.8,
    )

    assert report.batch is not None
    assert [i.job_id for i in report.batch.items] == [IDS[2], IDS[0]]
    assert [(r.index, r.reasons) for r in report.rejected] == [(1, ["low_preference"])]


def test_a_withdrawn_item_neither_halts_the_platform_nor_counts_as_contact() -> None:
    service, batch, approval = approved_batch([1, 2])
    withdrawn = [audit(batch, 1, OutreachResult.WITHDRAWN, NOW)]

    decision = service.next_item(
        batch, approval, platform="boss", audits=withdrawn, lease_held=True,
        now=NOW + timedelta(minutes=5),
    )

    assert decision.allowed and decision.item is not None and decision.item.number == 2
    assert batch.items[0].job_id not in contacted_job_ids(withdrawn)


def test_strategy_tags_ride_on_the_item_and_bind_its_digest() -> None:
    from jobagent.outreach.service import _digest, _job_content

    plain = build([draft(0)])
    tagged = build(
        [draft(0, variant="opening_b", hook_requirement="Agent 工作流设计", experiment_id="EXP_1")]
    )
    assert plain.batch is not None and tagged.batch is not None

    item = tagged.batch.items[0]
    assert (item.variant, item.hook_requirement, item.experiment_id) == (
        "opening_b",
        "Agent 工作流设计",
        "EXP_1",
    )
    assert item.item_digest != plain.batch.items[0].item_digest
    # An untagged item keeps the digest it always had, so stored batches stay valid.
    job = JOBS[IDS[0]]
    assert plain.batch.items[0].item_digest == _digest(
        {"job": _job_content(job), "platform": "boss", "text": GREETING}
    )


def test_a_batch_names_the_harness_version_it_was_drafted_under() -> None:
    report = OutreachService().build_batch(
        [draft(0)],
        jobs=JOBS,
        already_contacted=set(),
        confirmed_evidence_ids=set(),
        batch_id="OBATCH_001",
        created_at=NOW,
        harness_version="HVER_ABC",
    )
    assert report.batch is not None and report.batch.harness_version == "HVER_ABC"
    assert build([draft(0)]).batch.harness_version is None  # type: ignore[union-attr]


def test_a_greeting_the_person_rewrote_is_not_held_to_the_length_limit() -> None:
    long_text = GREETING + "我" * 80
    agent = build([draft(0, long_text)])
    person = build([draft(0, long_text, written_by="person")])

    assert agent.batch is None and agent.rejected[0].reasons == ["too_long"]
    assert person.batch is not None
    item = person.batch.items[0]
    assert item.written_by == "person"
    assert "本人改写" in OutreachService().ask(person.batch, asked_at=NOW).question
    # Who wrote it is part of what was approved.
    same_words_by_agent = build([draft(0)]).batch
    assert same_words_by_agent is not None
    rewritten = build([draft(0, written_by="person")]).batch
    assert rewritten is not None
    assert rewritten.items[0].item_digest != same_words_by_agent.items[0].item_digest
