"""Private initialization markers and read-only preparation; no task side effects."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from jobagent.errors import ContractValidationError, StorageError
from jobagent.rules.preparation import prepare_configuration
from jobagent.schemas.configuration import (
    BASE_CONFIGURATION_NAMES,
    ConfigurationInitialization,
    ConfigurationPreparationRequest,
    ConfigurationPreparationResult,
)
from jobagent.schemas.dynamic_rules import OwnerChangeRequest, RuleProposal
from jobagent.storage.database import Database
from jobagent.storage.rule_repository import SqliteRuleRepository


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _initialization(
    connection: sqlite3.Connection, candidate_id: str,
) -> ConfigurationInitialization | None:
    tables = _tables(connection)
    if "configuration_initializations" in tables:
        row = connection.execute(
            "SELECT rules_version, initialized_at FROM configuration_initializations "
            "WHERE candidate_id = ?", (candidate_id,),
        ).fetchone()
    elif "dynamic_rule_heads" in tables:
        # Reading an older profile must not itself migrate the database or ask again.
        row = connection.execute(
            "SELECT h.version, json_extract(v.snapshot_json, '$.effective_at') "
            "FROM dynamic_rule_heads h JOIN dynamic_rule_versions v ON v.version = h.version "
            "WHERE h.candidate_id = ?", (candidate_id,),
        ).fetchone()
    else:
        row = None
    return ConfigurationInitialization(
        candidate_id=candidate_id, rules_version=row[0], initialized_at=row[1],
    ) if row else None


def configuration_initialized(connection: sqlite3.Connection, candidate_id: str) -> bool:
    return _initialization(connection, candidate_id) is not None


def _owner_key(owner: OwnerChangeRequest, name: str) -> tuple[str, str, str, str, str, str]:
    return (
        owner.candidate_id, owner.source_reference, owner.actor_id, name,
        owner.scope, owner.run_id or "",
    )


def _owner_consumption(
    connection: sqlite3.Connection, owner: OwnerChangeRequest, name: str,
) -> tuple[str, str] | None:
    if "configuration_owner_consumptions" not in _tables(connection):
        return None
    row = connection.execute(
        "SELECT proposal_id, event_id FROM configuration_owner_consumptions "
        "WHERE candidate_id=? AND source_reference=? AND actor_id=? "
        "AND name=?", _owner_key(owner, name)[:4],
    ).fetchone()
    return (row[0], row[1]) if row else None


def require_owner_change_request(
    connection: sqlite3.Connection, proposal: RuleProposal, *, permanent: bool = False,
    allow_consumed_by: str | None = None,
) -> None:
    owner = proposal.request.owner_request
    if permanent and owner is not None and owner.scope == "round":
        raise ContractValidationError("A round-only change cannot update reusable configuration.")
    initialized = _initialization(connection, proposal.candidate_id)
    if initialized is not None and (
        owner is None or owner.requested_at < initialized.initialized_at
    ):
        raise ContractValidationError(
            "Initialized configuration requires a new explicit owner request.",
        )
    if owner is None:
        return
    consumed = _owner_consumption(connection, owner, proposal.request.name)
    if consumed is not None:
        if consumed == (proposal.proposal_id, allow_consumed_by):
            saved = connection.execute(
                "SELECT proposal_json FROM dynamic_rule_proposals WHERE proposal_id=?",
                (proposal.proposal_id,),
            ).fetchone()
            if saved and RuleProposal.model_validate_json(saved[0]) == proposal:
                return
        raise ContractValidationError("Owner request was already consumed for this variable.")
    current = SqliteRuleRepository._current(connection, proposal.candidate_id)
    source = current.provenance.get(proposal.request.name) if current else None
    if source is not None and owner.requested_at <= source.decided_at:
        raise ContractValidationError(
            "Owner request is stale or consumed; a newer explicit request is required.",
        )


def consume_owner_change_request(
    connection: sqlite3.Connection, proposal: RuleProposal, *, event_id: str,
) -> None:
    """Consume a named request inside the caller's transaction before promoting its head."""
    owner = proposal.request.owner_request
    if owner is None:
        return
    if not event_id.strip():
        raise ContractValidationError("Owner request consumption requires an actual event ID.")
    require_owner_change_request(connection, proposal, allow_consumed_by=event_id)
    if _owner_consumption(connection, owner, proposal.request.name) is not None:
        return
    connection.execute(
        "INSERT INTO configuration_owner_consumptions "
        "(candidate_id, source_reference, actor_id, name, scope, run_id, proposal_id, event_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (*_owner_key(owner, proposal.request.name), proposal.proposal_id, event_id),
    )


class SqliteConfigurationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def prepare(
        self, request: ConfigurationPreparationRequest, *, now: datetime | None = None,
    ) -> ConfigurationPreparationResult:
        now = now or datetime.now(UTC)
        if not self.database.path.exists():
            return prepare_configuration(request, None, initialized=False, now=now)
        try:
            uri = self.database.path.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                snapshot = SqliteRuleRepository._current(connection, request.candidate_id) \
                    if "dynamic_rule_heads" in _tables(connection) else None
                initialization = _initialization(connection, request.candidate_id)
                owner = request.owner_request
                consumed_names = {
                    name for name in owner.names
                    if _owner_consumption(connection, owner, name) is not None
                } if request.mode == "owner_requested_change" and owner else set()
        except sqlite3.Error as error:
            raise StorageError("Private configuration could not be read.") from error
        if (request.mode == "owner_requested_change"
                and initialization is not None and request.owner_request is not None
                and request.owner_request.requested_at < initialization.initialized_at):
            request = request.model_copy(update={
                "conflicts": [*request.conflicts, "owner_request_precedes_initialization"],
            })
        return prepare_configuration(request, snapshot, initialized=initialization is not None,
                                     now=now, consumed_names=consumed_names)

    def initialize(
        self, candidate_id: str, expected_version: str, *, now: datetime,
    ) -> ConfigurationInitialization:
        if now.tzinfo is None:
            raise ContractValidationError("Initialization time requires a timezone.")
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = SqliteRuleRepository._current(connection, candidate_id)
            if snapshot is None or snapshot.version != expected_version:
                raise ContractValidationError("Initialization requires the current rules version.")
            previous = _initialization(connection, candidate_id)
            if previous is not None:
                return previous
            missing = [name for name in BASE_CONFIGURATION_NAMES if name not in snapshot.values]
            if missing:
                raise ContractValidationError(
                    "Initial configuration has missing confirmed values.",
                    details={"missing": missing},
                )
            if now < snapshot.effective_at:
                raise ContractValidationError("Initialization cannot precede confirmed settings.")
            record = ConfigurationInitialization(
                candidate_id=candidate_id, rules_version=expected_version, initialized_at=now,
            )
            connection.execute(
                "INSERT INTO configuration_initializations VALUES (?, ?, ?)",
                (candidate_id, expected_version, now.isoformat()),
            )
        return record
