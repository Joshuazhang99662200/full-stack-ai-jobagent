"""Explicit private source adapters. Source SQL connections never migrate or create."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from jobagent.bridge.preference_memory import MarkdownPreferenceStore
from jobagent.digest import bytes_digest, canonical_digest, text_digest
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.candidate import CandidateProfile
from jobagent.schemas.memory import (
    MemoryConfig,
    MemoryItem,
    MemoryRead,
    MemorySource,
    MemorySourceRef,
)
from jobagent.schemas.message_diff import MessageRuleConfirmation, MessageRuleProposal
from jobagent.storage.database import LATEST_SCHEMA_VERSION, Database
from jobagent.storage.message_diff_repository import MessageDiffRepository


def private_path(path: Path, *, allow_root: bool = False) -> Path:
    resolved = path.resolve()
    workspace = Path.cwd().resolve()
    for root in (workspace / "candidate/private", workspace / ".jobagent"):
        actual = root.resolve()
        if (
            actual.is_relative_to(workspace)
            and resolved.is_relative_to(actual)
            and (allow_root or resolved != actual)
        ):
            return resolved
    raise ContractValidationError("Memory paths must remain in the private workspace.")


def validate_paths(config: MemoryConfig, store: Path) -> None:
    root = private_path(Path(config.private_root), allow_root=True)
    destination = private_path(store)
    if not destination.is_relative_to(root):
        raise ContractValidationError("Memory sidecar must remain inside its private root.")
    seen = set()
    for source in config.sources:
        path = source_path(config, source)
        aliases_store = path.exists() and destination.exists() and path.samefile(destination)
        if not path.is_relative_to(root) or path == destination or path in seen or aliases_store:
            raise ContractValidationError(
                "Memory source path conflicts or escapes its private root."
            )
        seen.add(path)


def source_path(config: MemoryConfig, source: MemorySource) -> Path:
    path = Path(source.path)
    return private_path(path if path.is_absolute() else Path(config.private_root) / path)


class _ReadDatabase(Database):
    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        super().__init__(path)
        self.connection = connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        yield self.connection


class PrivateSourceReader:
    def __init__(self, config: MemoryConfig, store: Path) -> None:
        validate_paths(config, store)
        self.config = config
        self.store = store

    def read(self, source: MemorySource) -> MemoryRead:
        validate_paths(self.config, self.store)
        if source not in self.config.sources or source.candidate_id != self.config.candidate_id:
            raise ContractValidationError("Memory source is not registered for this candidate.")
        ref = MemorySourceRef(
            **source.model_dump(exclude={"schema_version"}),
            state="not_integrated",
            evidence_level="unknown",
            diagnostics=["adapter_not_integrated"],
        )
        result = MemoryRead(source=ref)
        if source.kind not in {"preference_memory", "confirmed_rules", "legacy_inventory"}:
            return result
        path = source_path(self.config, source)
        ref.diagnostics = []
        if not path.exists():
            ref.state = "missing"
            return result
        if not path.is_file():
            ref.state = "invalid"
            ref.diagnostics = ["source_not_file"]
            return result
        try:
            if source.kind == "confirmed_rules":
                return self._confirmed(source, path, result)
            if path.stat().st_size > 20_000_000:
                raise ValueError("oversized source")
            raw = path.read_bytes()
            ref.digest = bytes_digest(raw)
            if source.kind == "legacy_inventory":
                ref.evidence_level = "host_reported"
                ref.state = "ready" if raw.strip() else "empty"
                ref.diagnostics = [
                    "inventory_only",
                    "owner_text_and_generation_payload_not_verified",
                ]
                return result
            memory = MarkdownPreferenceStore(path, source.candidate_id).parse_bytes(raw)
            ref.evidence_level = "validated_preference"
            ref.version = memory.version
            ref.count = len(memory.rules)
            ref.state = "ready" if memory.rules else "empty"
            result.items = [
                MemoryItem(
                    source_id=source.source_id,
                    item_id=r.rule_id,
                    candidate_id=memory.candidate_id,
                    task="search" if r.category == "jobs" else "greeting",
                    kind="soft_preference",
                    text=r.text,
                    scope=r.scope,
                    job_id=r.job_id,
                    condition=r.condition,
                )
                for r in memory.rules
            ]
            return result
        except (OSError, UnicodeError, sqlite3.Error):
            ref.state = "unreadable"
            ref.diagnostics = ["source_read_failed"]
        except (
            ValueError,
            JobAgentError,
            ValidationError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
        ):
            ref.state = "invalid"
            ref.diagnostics = ["source_validation_failed"]
        return result.model_copy(update={"items": []})

    def _confirmed(self, source: MemorySource, path: Path, result: MemoryRead) -> MemoryRead:
        ref = result.source
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {
                "message_diff_events",
                "message_rule_proposals",
                "message_rule_confirmations",
            }
            ref.version = "sqlite:" + str(connection.execute("PRAGMA user_version").fetchone()[0])
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if not 21 <= version <= LATEST_SCHEMA_VERSION:
                ref.state = "not_integrated"
                ref.diagnostics = ["source_schema_not_supported"]
                return result
            if not required <= tables:
                ref.state = "not_integrated"
                ref.diagnostics = ["confirmed_rule_tables_missing"]
                return result
            if "candidate_profiles" not in tables:
                ref.state = "not_integrated"
                ref.diagnostics = ["candidate_profiles_not_integrated"]
                return result
            profile = connection.execute(
                "SELECT profile_json FROM candidate_profiles WHERE candidate_id=?",
                (source.candidate_id,),
            ).fetchone()
            if profile is None:
                ref.state = "missing"
                ref.diagnostics = ["candidate_profile_missing"]
                return result
            if CandidateProfile.model_validate_json(profile[0]).id != source.candidate_id:
                raise ContractValidationError("Rule source candidate profile mismatches ownership.")
            # Read every candidate-bound link in one transaction. Embedded candidate fields
            # must agree with SQL ownership; candidate-filtered SQL alone is insufficient.
            provenance = {}
            proposals: dict[str, dict[str, object]] = {}
            for table, column, identity in (
                ("message_diff_events", "input_json", "event_id"),
                ("message_rule_proposals", "proposal_json", "proposal_id"),
                ("message_rule_confirmations", "confirmation_json", "confirmation_id"),
            ):
                values = []
                for row in connection.execute(
                    f"SELECT * FROM {table} WHERE candidate_id=? ORDER BY rowid",
                    (source.candidate_id,),
                ):
                    value = json.loads(row[column])
                    if (
                        value.get("candidate_id") != row["candidate_id"]
                        or value.get(identity) != row[identity]
                    ):
                        raise ContractValidationError(
                            "Rule chain identity mismatches its SQL owner."
                        )
                    if table == "message_rule_proposals":
                        if text_digest(value["rule_text"]) != value["rule_hash"]:
                            raise ContractValidationError("Rule text digest changed.")
                        if value.get("source_kind") != "pipeline_diagnosis":
                            proposal = MessageRuleProposal.model_validate(
                                {key: value[key] for key in MessageRuleProposal.model_fields}
                            )
                            if (
                                canonical_digest(proposal.model_dump(mode="json"))
                                != row["input_digest"]
                            ):
                                raise ContractValidationError("Rule proposal input digest changed.")
                        proposals[value["proposal_id"]] = value
                    if table == "message_rule_confirmations":
                        decision = MessageRuleConfirmation.model_validate(
                            {key: value[key] for key in MessageRuleConfirmation.model_fields}
                        )
                        proposal_value = proposals.get(decision.proposal_id)
                        if (
                            decision.proposal_id != row["proposal_id"]
                            or not decision.owner_text.strip()
                            or not decision.owner_reference.strip()
                            or not isinstance(value["accepted"], bool)
                            or proposal_value is None
                            or decision.rule_hash != proposal_value["rule_hash"]
                            or canonical_digest(decision.model_dump(mode="json"))
                            != row["input_digest"]
                        ):
                            raise ContractValidationError(
                                "Rule confirmation source binding changed."
                            )
                    values.append(value)
                provenance[table] = values
            rules = MessageDiffRepository(_ReadDatabase(path, connection)).confirmed_rules(
                source.candidate_id
            )
            ref.digest = canonical_digest(provenance)
            ref.count = len(rules)
            ref.evidence_level = "owner_confirmed"
            ref.state = "ready" if rules else "empty"
            for rule in rules:
                if rule.get("candidate_id") != source.candidate_id:
                    raise ContractValidationError("Rule belongs to another candidate.")
                scope: Literal["unsupported", "general"] = (
                    "unsupported" if rule.get("source_kind") == "pipeline_diagnosis" else "general"
                )
                result.items.append(
                    MemoryItem(
                        source_id=source.source_id,
                        item_id=str(rule["proposal_id"]),
                        candidate_id=source.candidate_id,
                        task="greeting",
                        kind="confirmed_rule",
                        text=str(rule["rule_text"]),
                        scope=scope,
                    )
                )
        return result
