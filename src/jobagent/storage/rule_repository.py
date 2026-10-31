"""Transactional, candidate-scoped dynamic rule history and notification receipts."""

import sqlite3
from datetime import datetime

from jobagent.errors import ContractValidationError
from jobagent.rules.service import (
    activate_proposal,
    change_notice,
    make_proposal,
    validate_snapshot,
)
from jobagent.schemas.dynamic_rules import (
    DynamicRuleSet,
    RuleChangeNotice,
    RuleConfirmation,
    RuleProposal,
)
from jobagent.storage.database import Database


class SqliteRuleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _current(connection: sqlite3.Connection, candidate_id: str) -> DynamicRuleSet | None:
        row = connection.execute(
            "SELECT v.snapshot_json FROM dynamic_rule_heads h JOIN dynamic_rule_versions v "
            "ON v.version=h.version WHERE h.candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        return validate_snapshot(DynamicRuleSet.model_validate_json(row[0])) if row else None

    def current(self, candidate_id: str) -> DynamicRuleSet | None:
        with self.database.connect() as connection:
            return self._current(connection, candidate_id)

    def save_proposal(self, proposal: RuleProposal) -> None:
        from jobagent.storage.configuration_repository import require_owner_change_request

        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            require_owner_change_request(connection, proposal)
            current = self._current(connection, proposal.candidate_id)
            expected = make_proposal(proposal.request, current, now=proposal.proposed_at)
            if proposal != expected:
                raise ContractValidationError("Original dynamic-rule question changed.")
            previous = connection.execute(
                "SELECT proposal_json FROM dynamic_rule_proposals WHERE proposal_id = ?",
                (proposal.proposal_id,),
            ).fetchone()
            body = proposal.model_dump_json()
            if previous and previous[0] != body:
                raise ContractValidationError("Proposal ID already contains different input.")
            connection.execute(
                "INSERT OR IGNORE INTO dynamic_rule_proposals VALUES (?, ?, ?)",
                (proposal.proposal_id, proposal.candidate_id, body),
            )

    def proposal(self, proposal_id: str) -> RuleProposal | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT proposal_json FROM dynamic_rule_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return RuleProposal.model_validate_json(row[0]) if row else None

    def approve(
        self,
        confirmation: RuleConfirmation,
        *,
        candidate_id: str,
    ) -> DynamicRuleSet:
        from jobagent.storage.configuration_repository import (
            consume_owner_change_request,
            require_owner_change_request,
        )

        confirmation = RuleConfirmation.model_validate(confirmation.model_dump(mode="json"))
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT proposal_json FROM dynamic_rule_proposals WHERE proposal_id=? "
                "AND candidate_id=?",
                (confirmation.proposal_id, candidate_id),
            ).fetchone()
            if row is None:
                raise ContractValidationError("No saved proposal in this candidate scope.")
            previous = connection.execute(
                "SELECT c.confirmation_json, v.snapshot_json FROM dynamic_rule_confirmations c "
                "JOIN dynamic_rule_versions v ON v.version=c.version WHERE c.proposal_id=?",
                (confirmation.proposal_id,),
            ).fetchone()
            if previous:
                if RuleConfirmation.model_validate_json(previous[0]) != confirmation:
                    raise ContractValidationError("Proposal already has a different confirmation.")
                return validate_snapshot(DynamicRuleSet.model_validate_json(previous[1]))
            proposal = RuleProposal.model_validate_json(row[0])
            require_owner_change_request(connection, proposal, permanent=True)
            snapshot = activate_proposal(
                proposal, confirmation, self._current(connection, candidate_id)
            )
            consume_owner_change_request(connection, proposal, event_id=proposal.proposal_id)
            notice = change_notice(proposal, snapshot)
            connection.execute(
                "INSERT INTO dynamic_rule_versions VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.version,
                    candidate_id,
                    proposal.proposal_id,
                    snapshot.model_dump_json(),
                    notice.model_dump_json(),
                ),
            )
            connection.execute(
                "INSERT INTO dynamic_rule_confirmations VALUES (?, ?, ?)",
                (proposal.proposal_id, snapshot.version, confirmation.model_dump_json()),
            )
            connection.execute(
                "INSERT INTO dynamic_rule_heads VALUES (?, ?) ON CONFLICT(candidate_id) "
                "DO UPDATE SET version=excluded.version",
                (candidate_id, snapshot.version),
            )
        return snapshot

    def history(self, candidate_id: str) -> list[DynamicRuleSet]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT snapshot_json FROM dynamic_rule_versions "
                "WHERE candidate_id=? ORDER BY rowid",
                (candidate_id,),
            ).fetchall()
        return [validate_snapshot(DynamicRuleSet.model_validate_json(row[0])) for row in rows]

    def pending_notices(self, candidate_id: str) -> list[RuleChangeNotice]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT v.notice_json FROM dynamic_rule_versions v LEFT JOIN "
                "dynamic_rule_announcements a ON a.version=v.version "
                "WHERE v.candidate_id=? AND a.version IS NULL ORDER BY v.rowid",
                (candidate_id,),
            ).fetchall()
        return [RuleChangeNotice.model_validate_json(row[0]) for row in rows]

    def acknowledge(
        self,
        candidate_id: str,
        version: str,
        *,
        reference: str,
        at: datetime,
    ) -> None:
        if not reference.strip() or at.tzinfo is None:
            raise ContractValidationError("Notification receipt requires a reference and time.")
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT snapshot_json FROM dynamic_rule_versions "
                "WHERE version=? AND candidate_id=?",
                (version, candidate_id),
            ).fetchone()
            if row is None:
                raise ContractValidationError("No rule version in this candidate scope.")
            snapshot = DynamicRuleSet.model_validate_json(row[0])
            if at < snapshot.effective_at:
                raise ContractValidationError("Notification cannot precede activation.")
            previous = connection.execute(
                "SELECT delivery_reference FROM dynamic_rule_announcements WHERE version=?",
                (version,),
            ).fetchone()
            if previous and previous[0] != reference:
                raise ContractValidationError("Announcement already has a different receipt.")
            connection.execute(
                "INSERT OR IGNORE INTO dynamic_rule_announcements VALUES (?, ?, ?, ?)",
                (version, candidate_id, reference, at.isoformat()),
            )
