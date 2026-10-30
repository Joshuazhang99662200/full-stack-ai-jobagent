# ruff: noqa: RUF001  -- Candidate-readable Markdown uses Chinese punctuation.
"""Verified owner events and versioned candidate-private Markdown preferences."""

import hashlib
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from jobagent.bridge.greeting_context import _owned, _real_job
from jobagent.capabilities import ReasoningProvider
from jobagent.errors import ContractValidationError
from jobagent.outreach.generation import content_digest
from jobagent.outreach.preference_memory import PreferenceLearner, memory_digest
from jobagent.outreach.service import policy_digest
from jobagent.schemas.candidate import CandidateProfile, EvidenceItem
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.outreach import OutreachAsk, OutreachBatch
from jobagent.schemas.preference_memory import PreferenceMemory
from jobagent.schemas.sourcing_feedback import PagedCardState, SourcingFeedback

_META = "\n<!-- typed-preference-memory -->\n```json\n"
_CHECKSUM = re.compile(r"\A<!-- preference-memory-sha256: ([a-f0-9]{64}) -->\n")


def _private(path: Path) -> Path:
    workspace = Path.cwd().resolve()
    resolved = path.resolve()
    roots = [workspace / "candidate" / "private", workspace / ".jobagent"]
    if not any(
        root.resolve().is_relative_to(workspace)
        and resolved.is_relative_to(root.resolve())
        and resolved != root.resolve()
        for root in roots
    ):
        raise ContractValidationError(
            "Preference memory must stay in the candidate-private workspace."
        )
    return resolved


def _display(text: str) -> str:
    return " ".join(text.split()).replace("<", "&lt;").replace(">", "&gt;")


def _body(memory: PreferenceMemory) -> str:
    lines = [
        "# 候选人偏好 Memory",
        "",
        f"- 候选人：`{_display(memory.candidate_id)}`",
        f"- 版本：`{_display(memory.version)}`",
        f"- 上一版：`{_display(memory.previous_version or '无')}`",
        f"- 更新时间：{memory.updated_at.isoformat()}",
        f"- 已消费事件：{len(memory.consumed_event_ids)}",
        "",
        "偏好仅影响选材、表达与岗位优先级，不确认事实或授予审批、发送权限。",
        "正文与元数据一并校验；手工修改会停止程序回读，避免忽略本人改动。",
        "",
    ]
    for category, label in [("jobs", "岗位偏好 jobs"), ("greetings", "招呼偏好 greetings")]:
        lines.extend([f"## {label}", ""])
        selected = [rule for rule in memory.rules if rule.category == category]
        if not selected:
            lines.extend(["暂无已归纳规则。", ""])
        for rule in selected:
            lines.extend(
                [
                    f"### {_display(rule.rule_id)}",
                    "",
                    f"- 偏好：{_display(rule.text)}",
                    f"- 范围：`{rule.scope}`；条件：{_display(rule.condition)}",
                    f"- 当前 JD：`{rule.job_id or '无指定岗位'}`",
                    "- 来源事件：" + "、".join(_display(x) for x in rule.source_event_ids),
                    f"- 更新时间：{rule.updated_at.isoformat()}",
                    "",
                ]
            )
    return "\n".join(lines) + _META + memory.model_dump_json(indent=2) + "\n```\n"


def _document(memory: PreferenceMemory) -> str:
    body = _body(memory)
    return (
        "<!-- preference-memory-sha256: "
        + hashlib.sha256(body.encode("utf-8")).hexdigest()
        + " -->\n"
        + body
    )


class MarkdownPreferenceStore:
    def __init__(self, path: Path, candidate_id: str) -> None:
        self.path = _private(path)
        self.candidate_id = candidate_id
        # Validate the identifier even for a not-yet-created memory.
        try:
            PreferenceMemory(candidate_id=candidate_id)
        except ValidationError:
            raise ContractValidationError(
                "The preference candidate identifier is invalid."
            ) from None

    def load(self) -> PreferenceMemory:
        if not self.path.exists():
            return PreferenceMemory(candidate_id=self.candidate_id)
        try:
            if self.path.stat().st_size > 2000000:
                raise ValueError("oversized memory")
            text = self.path.read_text(encoding="utf-8")
            match = _CHECKSUM.match(text)
            if match is None:
                raise ValueError("missing integrity header")
            body = text[match.end() :]
            if hashlib.sha256(body.encode("utf-8")).hexdigest() != match[1]:
                raise ValueError("modified body")
            metadata = re.search(re.escape(_META) + r"(.*)\n```\n\Z", body, flags=re.S)
            if metadata is None:
                raise ValueError("missing metadata")
            memory = PreferenceMemory.model_validate_json(metadata[1])
            if memory.candidate_id != self.candidate_id or _body(memory) != body:
                raise ValueError("modified metadata or candidate")
            return memory
        except (OSError, ValueError, ValidationError):
            raise ContractValidationError(
                "Preference memory integrity failed or the Markdown was manually modified."
            ) from None

    def save(self, memory: PreferenceMemory, *, expected_version: str) -> None:
        try:
            memory = PreferenceMemory.model_validate(memory.model_dump())
        except ValidationError:
            raise ContractValidationError(
                "Preference memory has invalid typed provenance."
            ) from None
        if memory.candidate_id != self.candidate_id:
            raise ContractValidationError("Preference memory belongs to another candidate.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = _private(self.path.with_suffix(self.path.suffix + ".lock"))
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ContractValidationError(
                "Preference memory is locked by a concurrent writer."
            ) from None
        temporary: Path | None = None
        try:
            os.close(descriptor)
            exists = self.path.exists()
            current = self.load()
            if current.version != expected_version:
                raise ContractValidationError("Preference memory changed concurrently; reload it.")
            if exists and current.version == memory.version:
                if memory_digest(current) != memory_digest(memory):
                    raise ContractValidationError(
                        "Preference memory changed without a new version."
                    )
                return
            if exists:
                old = self.path.read_bytes()
                history = _private(self.path.parent / "history")
                history.mkdir(parents=True, exist_ok=True)
                version = re.sub(r"[^A-Za-z0-9_-]", "_", current.version)[:60]
                backup = _private(
                    history
                    / (f"{self.path.stem}.{version}.{hashlib.sha256(old).hexdigest()[:16]}.md")
                )
                try:
                    with backup.open("xb") as file:
                        file.write(old)
                except FileExistsError:
                    if backup.read_bytes() != old:
                        raise ContractValidationError(
                            "Preference history content conflicts."
                        ) from None
            with NamedTemporaryFile(
                dir=self.path.parent, prefix=".preference-", suffix=".tmp", mode="wb", delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(_document(memory).encode("utf-8"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except OSError:
            raise ContractValidationError(
                "Preference memory could not be stored atomically."
            ) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)


def load_preference_events(database: Path, candidate_id: str) -> list[SourcingFeedback]:
    """Read source-bound real card decisions; never infer legacy feedback classes."""
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {
                "sourcing_feedback_events",
                "paged_card_events",
                "paged_card_states",
                "outreach_batches",
                "outreach_asks",
                "candidate_profiles",
                "evidence_items",
                "normalized_jobs",
            }
            if not required <= tables:
                return []
            profile_row = conn.execute(
                "SELECT profile_json FROM candidate_profiles WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if (
                profile_row is None
                or CandidateProfile.model_validate_json(profile_row[0]).id != candidate_id
            ):
                raise ContractValidationError("The preference candidate does not exist.")
            evidence = [
                EvidenceItem.model_validate_json(row[0])
                for row in conn.execute(
                    "SELECT evidence_json FROM evidence_items WHERE candidate_id=?",
                    (candidate_id,),
                )
            ]
            owned = {e.id for e in evidence if e.user_confirmed and e.confidence.value != "weak"}
            jobs = {
                job.id: job
                for job in (
                    NormalizedJob.model_validate_json(row[0])
                    for row in conn.execute("SELECT job_json FROM normalized_jobs")
                )
            }
            rows = conn.execute(
                "SELECT f.event_id,f.idempotency_key,f.source,f.occurred_at,f.event_json,"
                "e.message_id,s.state_json,b.batch_json,q.ask_json "
                "FROM sourcing_feedback_events f "
                "JOIN paged_card_events e ON e.event_id=f.event_id "
                "JOIN paged_card_states s ON s.message_id=e.message_id "
                "JOIN outreach_batches b ON b.batch_id=json_extract(s.state_json,'$.batch_id') "
                "JOIN outreach_asks q ON q.ask_id=json_extract(s.state_json,'$.ask_id') "
                "ORDER BY f.occurred_at,f.event_id"
            )
            result: list[SourcingFeedback] = []
            for row in rows:
                try:
                    event = SourcingFeedback.model_validate_json(row[4])
                    state = PagedCardState.model_validate_json(row[6])
                    batch = OutreachBatch.model_validate_json(row[7])
                    ask = OutreachAsk.model_validate_json(row[8])
                    job = jobs.get(event.job_id)
                    if (
                        event.candidate_id != candidate_id
                        or state.candidate_id != candidate_id
                        or state.demo_mode
                        or job is None
                        or not _real_job(job)
                        or event.event_id != row[0]
                        or event.idempotency_key != row[1]
                        or event.idempotency_key != event.event_id
                        or event.source != row[2]
                        or event.occurred_at != datetime.fromisoformat(row[3])
                        or state.message_id != row[5]
                        or state.batch_id != batch.batch_id
                        or state.ask_id != ask.ask_id
                        or ask.batch_id != batch.batch_id
                        or ask.batch_digest != batch.batch_digest
                        or ask.policy_digest != batch.policy_digest
                        or policy_digest(batch.policy) != batch.policy_digest
                        or content_digest([[i.number, i.item_digest] for i in batch.items])
                        != batch.batch_digest
                        or batch.created_at > ask.asked_at
                        or not ask.asked_at <= event.occurred_at < state.expires_at
                        or not event.jd_text
                        or not event.jd_text.strip()
                        or not event.job_title
                        or not event.company
                        or not event.original_text
                    ):
                        continue
                    for item in batch.items:
                        key = str(item.number)
                        words = state.drafts.get(key, item.text)
                        decision = {
                            "approve": "approved",
                            "revise": "revision_requested",
                            "decline": "declined",
                        }[event.action]
                        if (
                            item.job_id != event.job_id
                            or item.platform != event.source
                            or job.source != event.source
                            or not _owned(item, owned)
                            or item.text not in ask.question
                            or event.original_text != item.text
                            or state.decisions.get(key) != decision
                            or "sha256:" + hashlib.sha256(words.encode()).hexdigest()
                            != event.content_digest
                            or (event.action == "revise" and event.revised_text != words)
                            or (event.action != "revise" and event.revised_text is not None)
                            or (event.action == "approve" and words != event.original_text)
                        ):
                            continue
                        result.append(event)
                        break
                except (ValidationError, ValueError, TypeError):
                    continue
            return result
    except (sqlite3.Error, ValidationError, ValueError, OSError):
        raise ContractValidationError(
            "Preference events cannot be read from the private database."
        ) from None


def refresh_preference_memory(
    database: Path,
    path: Path,
    candidate_id: str,
    provider: ReasoningProvider,
    *,
    now: datetime | None = None,
) -> PreferenceMemory:
    store = MarkdownPreferenceStore(path, candidate_id)
    current = store.load()
    events = load_preference_events(database, candidate_id)
    updated = PreferenceLearner(provider).update(current, events, now=now or datetime.now(UTC))
    if not store.path.exists() or memory_digest(updated) != memory_digest(current):
        store.save(updated, expected_version=current.version)
    return updated
