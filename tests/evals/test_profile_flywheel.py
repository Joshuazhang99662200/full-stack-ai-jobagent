from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ApprovalRequiredError, ContractValidationError, StaleApprovalError
from jobagent.evals.profile import next_profile_version, profile_digest
from jobagent.evals.profile_flywheel import ProfileFlywheel
from jobagent.schemas.profile import (
    ProfileApplyResult,
    ProfileChange,
    ProfileField,
    ProfileProposalDraft,
    ProfileSnapshot,
    ProfileTarget,
)
from jobagent.schemas.sources import ProfileSectionSpec, ProfileSpec

AT = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
FLYWHEEL = ProfileFlywheel()
SPEC = ProfileSpec(
    edit_path="/web/geek/resume",
    sections=[
        ProfileSectionSpec(name="advantage", label="个人优势", max_chars=20, limit_source="shown"),
        ProfileSectionSpec(
            name="work_content",
            label="工作内容",
            max_chars=50,
            limit_source="shown",
            per_entry=True,
        ),
    ],
)


def snapshot(snapshot_id: str, at: datetime, **texts: str) -> ProfileSnapshot:
    fields = [ProfileField(name=name.replace("_1", "#1"), text=t) for name, t in texts.items()]
    return ProfileSnapshot(
        snapshot_id=snapshot_id,
        platform="boss",
        captured_at=at,
        fields=fields,
        digest=profile_digest(fields),
    )


BEFORE = snapshot("PROFSNAP_BEFORE", AT, advantage="主导 Agent 产品", work_content_1="做了 A")
BASE = next_profile_version(None, None, BEFORE)
assert BASE is not None
CURRENT = {"boss": (BASE, BEFORE)}


def draft(text: str = "主导金融 Agent 产品", **overrides: object) -> ProfileProposalDraft:
    values: dict[str, object] = {
        "targets": [
            ProfileTarget(
                platform="boss",
                base_version_id=BASE.version_id,
                changes=[ProfileChange(name="advantage", text=text)],
            )
        ],
        "rationale": "两阶段对比:先改个人优势",
        "evidence_ids": ["EVID_001"],
        "decision_rule": "B 期 M2 显著低于 A 期则保留,显著高于则回滚,否则延长一期",
    }
    values.update(overrides)
    return ProfileProposalDraft(**values)  # type: ignore[arg-type]


def propose(proposal_draft: ProfileProposalDraft | None = None, confirmed: set[str] | None = None):  # type: ignore[no-untyped-def]
    return FLYWHEEL.propose(
        proposal_draft or draft(),
        current=CURRENT,
        specs={"boss": SPEC},
        confirmed_evidence_ids={"EVID_001"} if confirmed is None else confirmed,
        proposal_id="PROFPROP_001",
        created_at=AT,
    )


def approved():  # type: ignore[no-untyped-def]
    proposal = propose()
    ask = FLYWHEEL.ask(proposal, current=CURRENT, asked_at=AT)
    approval = FLYWHEEL.approve(
        proposal, ask, answer="同意上线", current=CURRENT, approved_at=AT
    )
    return proposal, approval


def test_a_proposal_binds_the_exact_profile_each_board_should_end_up_with() -> None:
    proposal = propose()

    expected = profile_digest(
        [
            ProfileField(name="advantage", text="主导金融 Agent 产品"),
            ProfileField(name="work_content#1", text="做了 A"),
        ]
    )
    assert proposal.expected_digests == {"boss": expected}
    assert proposal.proposal_digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("proposal_draft", "confirmed", "problem"),
    [
        (draft("主导" * 20), None, "too_long:advantage"),
        (draft("主导 Agent 产品"), None, "no_change:advantage"),
        (draft("沉淀了 Agent 产品能力"), None, "self_justification:沉淀了"),
        (draft(), set(), "unconfirmed_evidence"),
    ],
)
def test_a_proposal_that_breaks_a_rule_is_refused_with_the_reason(
    proposal_draft: ProfileProposalDraft, confirmed: set[str] | None, problem: str
) -> None:
    with pytest.raises(ContractValidationError) as raised:
        propose(proposal_draft, confirmed)
    assert problem in raised.value.details["problems"]


def test_a_proposal_may_only_change_sections_the_board_already_has() -> None:
    unknown = draft(
        targets=[
            ProfileTarget(
                platform="boss",
                base_version_id=BASE.version_id,
                changes=[ProfileChange(name="hobby", text="跑步")],
            )
        ]
    )
    with pytest.raises(ContractValidationError) as raised:
        propose(unknown)
    assert "unknown_field:hobby" in raised.value.details["problems"]


def test_a_proposal_must_be_written_against_the_current_version() -> None:
    stale = draft(
        targets=[
            ProfileTarget(
                platform="boss",
                base_version_id="PROFVER_OLD",
                changes=[ProfileChange(name="advantage", text="主导金融 Agent 产品")],
            )
        ]
    )
    with pytest.raises(ContractValidationError) as raised:
        propose(stale)
    assert "stale_base:boss" in raised.value.details["problems"]


def test_the_question_shows_every_change_word_for_word_and_the_decision_rule() -> None:
    proposal = propose()
    ask = FLYWHEEL.ask(proposal, current=CURRENT, asked_at=AT)

    assert "主导 Agent 产品" in ask.question and "主导金融 Agent 产品" in ask.question
    assert proposal.decision_rule in ask.question
    assert ask.proposal_digest == proposal.proposal_digest


def test_approval_needs_the_question_first_the_person_s_words_and_a_current_base() -> None:
    proposal = propose()
    ask = FLYWHEEL.ask(proposal, current=CURRENT, asked_at=AT)

    with pytest.raises(ApprovalRequiredError):
        FLYWHEEL.approve(proposal, ask, answer=" ", current=CURRENT, approved_at=AT)
    other = ask.model_copy(update={"proposal_digest": "sha256:other"})
    with pytest.raises(StaleApprovalError):
        FLYWHEEL.approve(proposal, other, answer="同意", current=CURRENT, approved_at=AT)

    later = snapshot("PROFSNAP_LATER", AT + timedelta(hours=1), advantage="别人改的")
    moved = next_profile_version(BASE, BEFORE, later)
    assert moved is not None
    with pytest.raises(StaleApprovalError):
        FLYWHEEL.approve(
            proposal, ask, answer="同意", current={"boss": (moved, later)}, approved_at=AT
        )


def test_the_gate_hands_over_the_sections_to_fill_once_per_board() -> None:
    proposal, approval = approved()

    gate = FLYWHEEL.gate(proposal, approval, "boss", current=CURRENT, applications=[])
    assert gate.allowed and gate.expected_digest == proposal.expected_digests["boss"]
    assert [(f.name, f.text) for f in gate.fields] == [("advantage", "主导金融 Agent 产品")]

    assert FLYWHEEL.gate(proposal, None, "boss", current=CURRENT, applications=[]).reason == (
        "not_approved"
    )
    assert FLYWHEEL.gate(proposal, approval, "liepin", current=CURRENT, applications=[]).reason == (
        "not_in_proposal"
    )


def test_a_readback_matching_the_approved_profile_opens_an_agent_version() -> None:
    proposal, approval = approved()
    readback = snapshot(
        "PROFSNAP_AFTER", AT + timedelta(minutes=5),
        advantage="主导金融 Agent 产品", work_content_1="做了 A",
    )

    application, version = FLYWHEEL.record(
        proposal, approval, "boss", ProfileApplyResult.APPLIED,
        readback=readback, current=CURRENT, recorded_at=readback.captured_at,
    )

    assert application.result is ProfileApplyResult.APPLIED
    assert version is not None and version.origin == "agent"
    assert version.approval_id == approval.approval_id
    assert version.previous_version_id == BASE.version_id
    assert version.changed_fields == ["advantage"]
    gate = FLYWHEEL.gate(proposal, approval, "boss", current=CURRENT, applications=[application])
    assert gate.reason == "already_recorded"


def test_a_readback_that_differs_is_a_mismatch_and_no_agent_version() -> None:
    proposal, approval = approved()
    readback = snapshot(
        "PROFSNAP_AFTER",
        AT + timedelta(minutes=5),
        advantage="主导金融 Agent",
        work_content_1="做了 A",
    )

    application, version = FLYWHEEL.record(
        proposal, approval, "boss", ProfileApplyResult.APPLIED,
        readback=readback, current=CURRENT, recorded_at=readback.captured_at,
    )

    assert application.result is ProfileApplyResult.MISMATCH
    assert version is not None and version.origin == "external"


def test_applied_needs_a_readback_and_a_stop_needs_none() -> None:
    proposal, approval = approved()

    with pytest.raises(ContractValidationError):
        FLYWHEEL.record(
            proposal, approval, "boss", ProfileApplyResult.APPLIED,
            readback=None, current=CURRENT, recorded_at=AT,
        )
    application, version = FLYWHEEL.record(
        proposal, approval, "boss", ProfileApplyResult.INTERVENTION,
        readback=None, current=CURRENT, recorded_at=AT, reason="安全验证",
    )
    assert application.result is ProfileApplyResult.INTERVENTION and version is None
