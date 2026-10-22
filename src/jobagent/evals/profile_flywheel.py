# ruff: noqa: RUF001  -- Questions to the person are written in Chinese.
"""Put an approved online profile on a board, and know afterwards that it is there.

The profile is public: every recruiter on the board sees it. So the agent may
change it only through a proposal the person approved word for word, against the
version that is live now, and the change counts only once a read-back of the
board shows exactly the approved profile. Anything else is recorded as what it
is: a mismatch, a failure, or a page that wants a person.
"""

import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from jobagent.errors import ApprovalRequiredError, ContractValidationError, StaleApprovalError
from jobagent.evals.profile import next_profile_version, profile_digest
from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.profile import (
    ProfileApplication,
    ProfileApplyResult,
    ProfileApproval,
    ProfileAsk,
    ProfileField,
    ProfileGateDecision,
    ProfileProposal,
    ProfileProposalDraft,
    ProfileSnapshot,
    ProfileVersion,
)
from jobagent.schemas.sources import ProfileSpec

# A board's current profile: its latest version and the snapshot that opened it.
Current = Mapping[str, tuple[ProfileVersion, ProfileSnapshot]]

# Lines that certify the person instead of saying what they did; see
# references/optimizer/quality-gates.md and resume-grounding.md.
SELF_JUSTIFICATION = ("沉淀了", "具备", "练就", "熟练", "深度使用者", "直接来源")
_ENTRY_SUFFIX = re.compile(r"#\d+$")


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _short(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16].upper()


def _merged(snapshot: ProfileSnapshot, changes: Mapping[str, str]) -> list[ProfileField]:
    return [
        ProfileField(name=field.name, text=changes.get(field.name, field.text))
        for field in snapshot.fields
    ]


class ProfileFlywheel:
    def propose(
        self,
        draft: ProfileProposalDraft,
        *,
        current: Current,
        specs: Mapping[str, ProfileSpec | None],
        confirmed_evidence_ids: Collection[str],
        proposal_id: str,
        created_at: datetime,
    ) -> ProfileProposal:
        problems: list[str] = []
        if any(evidence not in confirmed_evidence_ids for evidence in draft.evidence_ids):
            problems.append("unconfirmed_evidence")
        expected: dict[str, str] = {}
        for target in draft.targets:
            live = current.get(target.platform)
            if live is None:
                problems.append(f"no_snapshot:{target.platform}")
                continue
            version, snapshot = live
            if target.base_version_id != version.version_id:
                problems.append(f"stale_base:{target.platform}")
                continue
            before = {field.name: field.text for field in snapshot.fields}
            spec = specs.get(target.platform)
            limits = {s.name: s.max_chars for s in spec.sections} if spec is not None else {}
            for change in target.changes:
                if change.name not in before:
                    problems.append(f"unknown_field:{change.name}")
                    continue
                if change.text == before[change.name]:
                    problems.append(f"no_change:{change.name}")
                limit = limits.get(_ENTRY_SUFFIX.sub("", change.name))
                if limit is not None and len(change.text) > limit:
                    problems.append(f"too_long:{change.name}")
                problems.extend(
                    f"self_justification:{phrase}"
                    for phrase in SELF_JUSTIFICATION
                    if phrase in change.text
                )
            changes = {change.name: change.text for change in target.changes}
            expected[target.platform] = profile_digest(_merged(snapshot, changes))
        if problems:
            raise ContractValidationError(
                "The profile proposal breaks the rules: " + ", ".join(problems),
                details={"problems": problems},
            )
        content = draft.model_dump(mode="json")
        return ProfileProposal(
            **draft.model_dump(),
            proposal_id=proposal_id,
            expected_digests=expected,
            proposal_digest=_digest({**content, "expected_digests": expected}),
            created_at=created_at,
        )

    def ask(self, proposal: ProfileProposal, *, current: Current, asked_at: datetime) -> ProfileAsk:
        """Every change, old and new, word for word, and the rule it will be judged by."""
        lines: list[str] = []
        for target in proposal.targets:
            _, snapshot = current[target.platform]
            before = {field.name: field.text for field in snapshot.fields}
            for change in target.changes:
                lines.append(
                    f"【{target.platform}｜{change.name}】\n"
                    f"  现在：{before.get(change.name, '')}\n"
                    f"  改为：{change.text}"
                )
        question = (
            "在线简历修改（公开内容，三站 HR 都会看到）：\n"
            + "\n".join(lines)
            + f"\n依据：{proposal.rationale}\n"
            f"判定规则：{proposal.decision_rule}\n"
            f"观察期：至少 {proposal.observation_workdays} 个工作日"
            f"且已读样本 ≥ {proposal.min_reads}\n"
            "回复“同意”即批准按以上原文上线；满足判定规则的回滚目标是修改前的快照版本。"
        )
        return ProfileAsk(
            ask_id=f"PROFASK_{proposal.proposal_id.removeprefix('PROFPROP_')}",
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.proposal_digest,
            question=question,
            asked_at=asked_at,
        )

    def approve(
        self,
        proposal: ProfileProposal,
        ask: ProfileAsk,
        *,
        answer: str,
        current: Current,
        approved_at: datetime,
        channel: ApprovalChannel = ApprovalChannel.AGENT_RELAY,
    ) -> ProfileApproval:
        details = {"proposal_id": proposal.proposal_id, "ask_id": ask.ask_id}
        if ask.proposal_id != proposal.proposal_id or ask.proposal_digest != (
            proposal.proposal_digest
        ):
            raise StaleApprovalError(
                "The question was about a different version of this proposal.", details=details
            )
        if not answer.strip():
            raise ApprovalRequiredError(
                "The approval must carry the person's own answer.", details=details
            )
        if self._stale_platforms(proposal, current):
            raise StaleApprovalError(
                "A board's profile changed after the proposal was written.",
                details={**details, "platforms": self._stale_platforms(proposal, current)},
            )
        return ProfileApproval(
            approval_id=f"PROFAPPR_{proposal.proposal_id.removeprefix('PROFPROP_')}",
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.proposal_digest,
            ask_id=ask.ask_id,
            channel=channel,
            attestation=answer.strip(),
            approved_at=approved_at,
        )

    def gate(
        self,
        proposal: ProfileProposal,
        approval: ProfileApproval | None,
        platform: str,
        *,
        current: Current,
        applications: Sequence[ProfileApplication],
    ) -> ProfileGateDecision:
        """Whether this board may be edited now, and with exactly which words."""
        target = next((t for t in proposal.targets if t.platform == platform), None)
        if target is None:
            return ProfileGateDecision(allowed=False, reason="not_in_proposal", platform=platform)
        if approval is None or approval.proposal_digest != proposal.proposal_digest:
            return ProfileGateDecision(allowed=False, reason="not_approved", platform=platform)
        if any(
            a.platform == platform and a.proposal_id == proposal.proposal_id
            for a in applications
        ):
            return ProfileGateDecision(allowed=False, reason="already_recorded", platform=platform)
        if platform in self._stale_platforms(proposal, current):
            return ProfileGateDecision(allowed=False, reason="stale_base", platform=platform)
        return ProfileGateDecision(
            allowed=True,
            platform=platform,
            fields=[ProfileField(name=c.name, text=c.text) for c in target.changes],
            expected_digest=proposal.expected_digests[platform],
        )

    def record(
        self,
        proposal: ProfileProposal,
        approval: ProfileApproval,
        platform: str,
        result: ProfileApplyResult,
        *,
        readback: ProfileSnapshot | None,
        current: Current,
        recorded_at: datetime,
        reason: str | None = None,
    ) -> tuple[ProfileApplication, ProfileVersion | None]:
        """Record one attempt. `applied` stands only if the read-back is the approved profile."""
        if result is ProfileApplyResult.APPLIED and readback is None:
            raise ContractValidationError(
                "An applied profile needs a read-back of the board.",
                details={"proposal_id": proposal.proposal_id, "platform": platform},
            )
        version: ProfileVersion | None = None
        if readback is not None:
            live = current.get(platform)
            previous, previous_snapshot = live if live is not None else (None, None)
            version = next_profile_version(previous, previous_snapshot, readback)
            matches = readback.digest == proposal.expected_digests.get(platform)
            if result is ProfileApplyResult.APPLIED and not matches:
                result = ProfileApplyResult.MISMATCH
                reason = reason or "read-back differs from the approved profile"
            if result is ProfileApplyResult.APPLIED and version is not None:
                version = version.model_copy(
                    update={
                        "origin": "agent",
                        "approval_id": approval.approval_id,
                        "proposal_id": proposal.proposal_id,
                    }
                )
        application = ProfileApplication(
            application_id=f"PROFAPP_{_short(f'{proposal.proposal_id}|{platform}')}",
            proposal_id=proposal.proposal_id,
            approval_id=approval.approval_id,
            platform=platform,
            result=result,
            readback_snapshot_id=readback.snapshot_id if readback is not None else None,
            reason=reason,
            recorded_at=recorded_at,
        )
        return application, version

    @staticmethod
    def _stale_platforms(proposal: ProfileProposal, current: Current) -> list[str]:
        return [
            target.platform
            for target in proposal.targets
            if target.platform not in current
            or current[target.platform][0].version_id != target.base_version_id
        ]
