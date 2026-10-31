"""Atomic admission, actual dispatch metering and immutable MCP observations."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from jobagent.errors import ContractValidationError, StorageError
from jobagent.harness.runtime import runtime_fingerprint
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.mcp_calls import bind_mcp_round
from jobagent.jobs.sourcing import SOURCING_DAY, refusal_reason
from jobagent.schemas.mcp_calls import (
    McpBudget,
    McpCallReceipt,
    McpCallReconciliation,
    McpCallRequest,
    McpDeliveryHandoff,
    McpDeliveryIntent,
    McpDeliveryObservation,
    McpProviderResult,
    McpRound,
    McpRoundRequest,
)
from jobagent.schemas.sourcing import SourcingAttempt, SourcingAttemptRequest, SourcingQueryCapture
from jobagent.storage.configuration_repository import configuration_initialized
from jobagent.storage.database import Database
from jobagent.storage.pipeline_policy import current_rule_snapshot
from jobagent.storage.query_repository import SqliteQueryRepository
from jobagent.storage.sourcing_repository import SqliteSourcingRepository


def _day(now: datetime) -> str:
    if now.tzinfo is None:
        raise ContractValidationError("MCP operations require an aware program clock.")
    return now.astimezone(SOURCING_DAY).date().isoformat()


class SqliteMcpRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.sourcing = SqliteSourcingRepository(database)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        except sqlite3.Error as error:
            raise StorageError("MCP ledger unavailable; no automatic retry.") from error

    @staticmethod
    def _run(connection: sqlite3.Connection, run_id: str) -> McpRound:
        row = connection.execute(
            "SELECT run_json FROM mcp_rounds WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("Unknown MCP round.")
        return McpRound.model_validate_json(row[0])

    def get_round(self, run_id: str) -> McpRound:
        with self.database.connect() as connection:
            return self._run(connection, run_id)

    def _current(self, connection: sqlite3.Connection, run: McpRound, *, now: datetime) -> None:
        rules = current_rule_snapshot(connection, run.candidate_id)
        if rules is None or not configuration_initialized(connection, run.candidate_id):
            raise ContractValidationError("MCP requires an initialized confirmed profile.")
        request = McpRoundRequest.model_validate(
            run.model_dump(include=set(McpRoundRequest.model_fields)),
        )
        bound = bind_mcp_round(request, rules, now=now, code_revision=runtime_fingerprint())
        if bound.model_dump(exclude={"opened_at"}) != run.model_dump(exclude={"opened_at"}):
            raise ContractValidationError("MCP frozen configuration changed.")
        source = self.sourcing._get_run(connection, run.sourcing_run_id)
        self.sourcing._configured_request(connection, source, now=now)
        if (
            source.candidate_id != run.candidate_id
            or source.source != run.source
            or source.rules_version != run.rules_version
            or source.code_revision != run.code_revision
        ):
            raise ContractValidationError("MCP round differs from its configured sourcing round.")

    @staticmethod
    def _closed(connection: sqlite3.Connection, run_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM mcp_round_closures WHERE run_id=?",
                (run_id,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _halted(connection: sqlite3.Connection, source: str, now: datetime) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sourcing_read_halts WHERE source=? AND platform_day=?",
                (source, _day(now)),
            ).fetchone()
            is not None
        )

    def _open(self, connection: sqlite3.Connection, run: McpRound, *, now: datetime) -> None:
        if self._closed(connection, run.run_id):
            raise ContractValidationError("MCP round is closed; its facts cannot change.")
        self._current(connection, run, now=now)
        if now < run.opened_at or _day(now) != _day(run.opened_at):
            raise ContractValidationError("MCP round execution day expired.")
        if self._halted(connection, run.source, now):
            raise ContractValidationError("MCP source is halted for this platform day.")

    def start_round(self, request: McpRoundRequest, *, now: datetime) -> McpRound:
        request = McpRoundRequest.model_validate(request.model_dump(mode="json"))
        _day(now)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self._write() as connection:
            rules = current_rule_snapshot(connection, request.candidate_id)
            if rules is None:
                raise ContractValidationError("MCP needs confirmed explicit parameters.")
            run = bind_mcp_round(request, rules, now=now, code_revision=runtime_fingerprint())
            self._current(connection, run, now=now)
            old = connection.execute(
                "SELECT request_digest,run_json FROM mcp_rounds WHERE run_id=?",
                (run.run_id,),
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise ContractValidationError("MCP run ID already contains different input.")
                return McpRound.model_validate_json(old[1])
            if connection.execute(
                "SELECT 1 FROM mcp_rounds WHERE json_extract(run_json,'$.sourcing_run_id')=?",
                (run.sourcing_run_id,),
            ).fetchone():
                raise ContractValidationError(
                    "The sourcing round is already bound to its MCP round; reuse that binding.",
                )
            connection.execute(
                "INSERT INTO mcp_rounds VALUES (?,?,?,?,?)",
                (
                    run.run_id,
                    run.candidate_id,
                    run.source,
                    digest,
                    run.model_dump_json(),
                ),
            )
        return run

    def _budget(self, connection: sqlite3.Connection, run: McpRound) -> McpBudget:
        active = connection.execute(
            "SELECT previous_run_id,previous_delivery_debit FROM mcp_round_activations "
            "WHERE run_id=?",
            (run.run_id,),
        ).fetchone()
        calls = int(
            connection.execute(
                "SELECT count(*) FROM mcp_dispatches d JOIN mcp_calls c ON c.call_id=d.call_id "
                "WHERE c.run_id=?",
                (run.run_id,),
            ).fetchone()[0]
        )
        base = run.liepin_call_limit or run.mcp_total
        debit = int(active[1]) if active else 0
        starting = max(0, base - debit)
        return McpBudget(
            run_id=run.run_id,
            candidate_id=run.candidate_id,
            source=run.source,
            rules_version=run.rules_version,
            code_revision=run.code_revision,
            activated=active is not None,
            closed=self._closed(connection, run.run_id),
            base_allowance=base,
            previous_run_id=active[0] if active else None,
            previous_delivery_debit=debit,
            starting_remaining=starting,
            actual_calls=calls,
            search_view_calls=calls,
            mcp_total=run.mcp_total,
            remaining=min(max(0, run.mcp_total - calls), max(0, starting - calls)),
            max_parallel=run.max_parallel,
            batch_size=run.batch_size,
            halted=self._halted(connection, run.source, run.opened_at),
        )

    def status(self, run_id: str) -> McpBudget:
        with self.database.connect() as connection:
            return self._budget(connection, self._run(connection, run_id))

    @staticmethod
    def _receipt(connection: sqlite3.Connection, call_id: str) -> McpCallReceipt | None:
        row = connection.execute(
            "SELECT coalesce(x.receipt_json,r.receipt_json) FROM mcp_results r "
            "LEFT JOIN mcp_reconciliations x ON x.call_id=r.call_id WHERE r.call_id=?",
            (call_id,),
        ).fetchone()
        return McpCallReceipt.model_validate_json(row[0]) if row else None

    @staticmethod
    def _unresolved(connection: sqlite3.Connection, run_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM mcp_calls c LEFT JOIN mcp_results r ON r.call_id=c.call_id "
                "LEFT JOIN mcp_reconciliations x ON x.call_id=c.call_id "
                "WHERE c.run_id=? AND (r.call_id IS NULL "
                "OR json_extract(coalesce(x.receipt_json,r.receipt_json),'$.status')='unknown') "
                "LIMIT 1",
                (run_id,),
            ).fetchone()
            is not None
        )

    def open_batch(
        self,
        requests: list[McpCallRequest],
        *,
        now: datetime,
    ) -> tuple[McpRound, list[McpCallReceipt] | None]:
        requests = [
            McpCallRequest.model_validate(item.model_dump(mode="json")) for item in requests
        ]
        if not requests:
            raise ContractValidationError("An MCP batch needs exact requests.")
        first = requests[0]
        if len({item.call_id for item in requests}) != len(requests) or any(
            (item.run_id, item.batch_id) != (first.run_id, first.batch_id) for item in requests
        ):
            raise ContractValidationError("A batch requires one round and unique call IDs.")
        digest = canonical_digest([item.model_dump(mode="json") for item in requests])
        with self._write() as connection:
            run = self._run(connection, first.run_id)
            old = connection.execute(
                "SELECT request_digest FROM mcp_batches WHERE batch_id=?",
                (first.batch_id,),
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise ContractValidationError("MCP batch already contains different input.")
                saved = [self._receipt(connection, item.call_id) for item in requests]
                if all(saved):
                    receipts = [row for row in saved if row]
                    if all(item.status != "unknown" for item in receipts):
                        return run, receipts
                raise ContractValidationError("MCP batch has an unresolved/unknown execution.")
            self._open(connection, run, now=now)
            if len(requests) > run.batch_size:
                raise ContractValidationError("MCP batch exceeds its confirmed batch size.")
            if self._unresolved(connection, run.run_id):
                raise ContractValidationError(
                    "Previous MCP batch is unresolved; batches are serial."
                )
            connection.execute(
                "INSERT INTO mcp_batches VALUES (?,?,?,?)",
                (
                    first.batch_id,
                    run.run_id,
                    digest,
                    now.isoformat(),
                ),
            )
            for item in requests:
                if connection.execute(
                    "SELECT 1 FROM mcp_calls WHERE call_id=?",
                    (item.call_id,),
                ).fetchone():
                    raise ContractValidationError("An MCP call ID cannot execute another input.")
                connection.execute(
                    "INSERT INTO mcp_calls VALUES (?,?,?,?,?)",
                    (
                        item.call_id,
                        item.batch_id,
                        item.run_id,
                        item.model_dump_json(),
                        now.isoformat(),
                    ),
                )
        return run, None

    def _activate(self, connection: sqlite3.Connection, run: McpRound, *, now: datetime) -> None:
        if connection.execute(
            "SELECT 1 FROM mcp_round_activations WHERE run_id=?",
            (run.run_id,),
        ).fetchone():
            return
        previous = connection.execute(
            "SELECT a.run_id FROM mcp_round_activations a JOIN mcp_rounds r ON r.run_id=a.run_id "
            "WHERE r.candidate_id=? AND r.source=? ORDER BY a.sequence DESC LIMIT 1",
            (run.candidate_id, run.source),
        ).fetchone()
        previous_id = previous[0] if previous else None
        if run.previous_run_id is not None and run.previous_run_id != previous_id:
            raise ContractValidationError(
                "Previous MCP round is not the authoritative predecessor."
            )
        debit = 0
        if previous_id is not None:
            closed = connection.execute(
                "SELECT successful_deliveries FROM mcp_round_closures WHERE run_id=?",
                (previous_id,),
            ).fetchone()
            if closed is None:
                raise ContractValidationError("Previous MCP round must be closed and resolved.")
            if run.source == "liepin":
                debit = int(closed[0])
        connection.execute(
            "INSERT INTO mcp_round_activations "
            "(run_id,previous_run_id,previous_delivery_debit,activated_at) VALUES (?,?,?,?)",
            (run.run_id, previous_id, debit, now.isoformat()),
        )

    @staticmethod
    def _call(connection: sqlite3.Connection, call_id: str) -> tuple[McpCallRequest, datetime]:
        row = connection.execute(
            "SELECT request_json,admitted_at FROM mcp_calls WHERE call_id=?",
            (call_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("MCP dispatch needs an admitted exact call.")
        return McpCallRequest.model_validate_json(row[0]), datetime.fromisoformat(row[1])

    def mark_dispatched(self, call_id: str, *, now: datetime) -> None:
        with self._write() as connection:
            request, admitted_at = self._call(connection, call_id)
            run = self._run(connection, request.run_id)
            self._open(connection, run, now=now)
            if now < admitted_at:
                raise ContractValidationError("MCP dispatch cannot precede its admission.")
            if connection.execute(
                "SELECT 1 FROM mcp_dispatches WHERE call_id=? UNION "
                "SELECT 1 FROM mcp_results WHERE call_id=?",
                (call_id, call_id),
            ).fetchone():
                raise ContractValidationError("MCP call already dispatched or completed.")
            self._activate(connection, run, now=now)
            budget = self._budget(connection, run)
            if budget.remaining == 0:
                raise ContractValidationError("MCP/source call allowance limit is exhausted.")
            parallel = connection.execute(
                "SELECT count(*) FROM mcp_dispatches d JOIN mcp_calls c ON c.call_id=d.call_id "
                "LEFT JOIN mcp_results r ON r.call_id=c.call_id "
                "WHERE c.run_id=? AND r.call_id IS NULL",
                (run.run_id,),
            ).fetchone()[0]
            if parallel >= run.max_parallel:
                raise ContractValidationError("MCP parallel limit is exhausted.")
            source = self.sourcing._get_run(connection, run.sourcing_run_id)
            target = SourcingAttemptRequest(
                attempt_id="MCP_" + call_id,
                run_id=source.run_id,
                kind="query" if request.operation == "search" else "detail",
                search_term=request.search_term,
                source_job_id=request.source_job_id,
                url=request.target_url,
            )
            source_budget = self.sourcing._budget(
                connection,
                source.source,
                source.daily_detail_limit,
                now,
            )
            queries, details = self.sourcing._round_counts(connection, source.run_id)
            refusal = refusal_reason(
                target, source, source_budget, query_count=queries, detail_count=details, now=now
            )
            if refusal:
                raise ContractValidationError("MCP shared sourcing budget refused: " + refusal)
            attempt = SourcingAttempt(
                **target.model_dump(exclude={"schema_version"}),
                source=run.source,
                occurred_at=now.astimezone(UTC),
            )
            connection.execute(
                "INSERT INTO sourcing_attempts VALUES (?,?,?,?,?,?)",
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.source,
                    attempt.kind,
                    attempt.occurred_at.isoformat(),
                    attempt.model_dump_json(),
                ),
            )
            connection.execute(
                "INSERT INTO mcp_dispatches VALUES (?,?,?)",
                (
                    call_id,
                    now.isoformat(),
                    attempt.attempt_id,
                ),
            )
            if request.operation == "search":
                connection.execute(
                    "INSERT INTO sourcing_query_claims VALUES (?,?,?)",
                    (
                        attempt.attempt_id,
                        canonical_digest(request.model_dump(mode="json")),
                        now.isoformat(),
                    ),
                )

    @staticmethod
    def _halt(connection: sqlite3.Connection, source: str, reason: str, *times: datetime) -> None:
        for at in times:
            connection.execute(
                "INSERT OR IGNORE INTO sourcing_read_halts VALUES (?,?,?)",
                (
                    source,
                    _day(at),
                    reason,
                ),
            )

    def finish(self, call_id: str, result: McpProviderResult, *, now: datetime) -> McpCallReceipt:
        _day(now)
        digest = canonical_digest(result.model_dump(mode="json"))
        with self._write() as connection:
            request, admitted_at = self._call(connection, call_id)
            run = self._run(connection, request.run_id)
            old = connection.execute(
                "SELECT result_digest,receipt_json FROM mcp_results WHERE call_id=?",
                (call_id,),
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise ContractValidationError("MCP call already contains a different result.")
                return McpCallReceipt.model_validate_json(old[1])
            dispatch = connection.execute(
                "SELECT dispatched_at,sourcing_attempt_id FROM mcp_dispatches WHERE call_id=?",
                (call_id,),
            ).fetchone()
            at = datetime.fromisoformat(dispatch[0]) if dispatch else None
            if now < (at or admitted_at):
                raise ContractValidationError("MCP result cannot predate its actual attempt.")
            status = result.status if dispatch else "not_called"
            if dispatch is None and result.status == "success":
                raise ContractValidationError("MCP success requires an actual dispatch.")
            if dispatch and result.error_code == "429001":
                status = "gate"
                result = result.model_copy(update={"status": "gate"})
            if dispatch and status in {"gate", "unknown", "already_applied", "blocked"}:
                self._halt(connection, run.source, status, at or now, now)
            selection = None
            if dispatch and request.operation == "search" and status == "success":
                if result.listings is None or not result.loaded:
                    raise ContractValidationError(
                        "Successful MCP search needs loaded real listings."
                    )
                selection = SqliteQueryRepository(self.database).take_in(
                    connection,
                    SourcingQueryCapture(
                        attempt_id=dispatch[1],
                        items=result.listings,
                        loaded=True,
                        access_state="authenticated",
                        next_cursor=result.next_cursor,
                    ),
                    now=now,
                )
                # Only the selected front rows are returned for consumption; raw payload
                # cannot supply an alternative unbounded list beside the actual receipt.
                result = result.model_copy(update={"payload": None, "listings": selection.items})
            receipt = McpCallReceipt(
                call_id=call_id,
                run_id=run.run_id,
                batch_id=request.batch_id,
                operation=request.operation,
                admitted_at=admitted_at,
                dispatched_at=at,
                completed_at=now,
                dispatched=dispatch is not None,
                status=status,
                result=result,
                selection=selection,
                budget=self._budget(connection, run),
            )
            connection.execute(
                "INSERT INTO mcp_results VALUES (?,?,?)",
                (
                    call_id,
                    digest,
                    receipt.model_dump_json(),
                ),
            )
            return receipt

    def close_round(self, run_id: str, *, now: datetime) -> McpBudget:
        with self._write() as connection:
            run = self._run(connection, run_id)
            if self._closed(connection, run_id):
                return self._budget(connection, run)
            pending = connection.execute(
                "SELECT 1 FROM mcp_delivery_actions a LEFT JOIN mcp_delivery_observations o "
                "ON o.action_id=a.action_id LEFT JOIN mcp_delivery_reconciliations x "
                "ON x.action_id=a.action_id WHERE a.run_id=? AND (o.action_id IS NULL "
                "OR json_extract(coalesce(x.observation_json,o.observation_json), "
                "'$.status')='unknown') LIMIT 1",
                (run_id,),
            ).fetchone()
            if self._unresolved(connection, run_id) or pending:
                raise ContractValidationError("MCP round has unresolved/unknown outcomes.")
            if now.tzinfo is None or now < run.opened_at:
                raise ContractValidationError("MCP closure requires an actual chronological time.")
            count = connection.execute(
                "SELECT count(*) FROM mcp_delivery_observations o JOIN mcp_delivery_actions a "
                "ON a.action_id=o.action_id LEFT JOIN mcp_delivery_reconciliations x "
                "ON x.action_id=o.action_id WHERE a.run_id=? "
                "AND json_extract(coalesce(x.observation_json,o.observation_json),"
                "'$.status')='sent'",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO mcp_round_closures VALUES (?,?,?)",
                (
                    run_id,
                    now.isoformat(),
                    count,
                ),
            )
            return self._budget(connection, run)

    def prepare_delivery(
        self,
        intent: McpDeliveryIntent,
        *,
        now: datetime,
    ) -> McpDeliveryHandoff:
        intent = McpDeliveryIntent.model_validate(intent.model_dump(mode="json"))
        with self._write() as connection:
            run = self._run(connection, intent.run_id)
            self._open(connection, run, now=now)
            if run.source != "liepin" or run.delivery_spacing_seconds is None:
                raise ContractValidationError("Confirmed Liepin delivery spacing is required.")
            if not self._budget(connection, run).activated:
                raise ContractValidationError(
                    "Delivery handoff requires an actually activated round."
                )
            old = connection.execute(
                "SELECT intent_json,prepared_at FROM mcp_delivery_actions WHERE action_id=?",
                (intent.action_id,),
            ).fetchone()
            if old:
                if McpDeliveryIntent.model_validate_json(old[0]) != intent:
                    raise ContractValidationError(
                        "Delivery action already contains different input."
                    )
                return McpDeliveryHandoff(intent=intent, prepared_at=old[1])
            prior = connection.execute(
                "SELECT a.prepared_at,coalesce(x.observation_json,o.observation_json) "
                "FROM mcp_delivery_actions a "
                "JOIN mcp_rounds r ON r.run_id=a.run_id LEFT JOIN mcp_delivery_observations o "
                "ON o.action_id=a.action_id LEFT JOIN mcp_delivery_reconciliations x "
                "ON x.action_id=a.action_id WHERE r.candidate_id=? AND r.source=? "
                "ORDER BY a.rowid DESC LIMIT 1",
                (run.candidate_id, run.source),
            ).fetchone()
            if prior:
                observation = (
                    McpDeliveryObservation.model_validate_json(prior[1]) if prior[1] else None
                )
                if observation is None or not observation.positive_readback:
                    raise ContractValidationError("Previous delivery requires positive readback.")
                if observation.status in {"unknown", "blocked", "already_applied", "gate"}:
                    raise ContractValidationError("Previous delivery requires a hard stop.")
                if now < observation.occurred_at + timedelta(seconds=run.delivery_spacing_seconds):
                    raise ContractValidationError("Delivery spacing has not elapsed.")
            connection.execute(
                "INSERT INTO mcp_delivery_actions VALUES (?,?,?,?)",
                (
                    intent.action_id,
                    run.run_id,
                    intent.model_dump_json(),
                    now.isoformat(),
                ),
            )
            return McpDeliveryHandoff(intent=intent, prepared_at=now)

    def record_delivery(
        self,
        observation: McpDeliveryObservation,
        *,
        now: datetime,
    ) -> McpDeliveryObservation:
        observation = McpDeliveryObservation.model_validate(observation.model_dump(mode="json"))
        with self._write() as connection:
            row = connection.execute(
                "SELECT intent_json,prepared_at FROM mcp_delivery_actions WHERE action_id=?",
                (observation.action_id,),
            ).fetchone()
            if row is None:
                raise ContractValidationError("Observed delivery needs its exact host handoff.")
            intent = McpDeliveryIntent.model_validate_json(row[0])
            run = self._run(connection, intent.run_id)
            old = connection.execute(
                "SELECT observation_json FROM mcp_delivery_observations WHERE action_id=?",
                (observation.action_id,),
            ).fetchone()
            if old:
                if McpDeliveryObservation.model_validate_json(old[0]) != observation:
                    raise ContractValidationError(
                        "Delivery observation already contains different facts."
                    )
                return observation
            if self._closed(connection, run.run_id):
                raise ContractValidationError("Closed MCP round delivery facts are frozen.")
            if (
                observation.run_id != run.run_id
                or observation.source_job_id != intent.source_job_id
                or now.tzinfo is None
                or observation.observed_at > now
                or observation.occurred_at < datetime.fromisoformat(row[1])
            ):
                raise ContractValidationError(
                    "Delivery observation has wrong target or chronology."
                )
            self._unique_delivery(connection, observation)
            if observation.status in {"unknown", "blocked", "already_applied", "gate"}:
                self._halt(
                    connection,
                    run.source,
                    observation.status,
                    observation.occurred_at,
                    observation.observed_at,
                )
            connection.execute(
                "INSERT INTO mcp_delivery_observations VALUES (?,?,?)",
                (
                    observation.action_id,
                    observation.external_reference,
                    observation.model_dump_json(),
                ),
            )
            return observation

    @staticmethod
    def _unique_delivery(
        connection: sqlite3.Connection,
        observation: McpDeliveryObservation,
    ) -> None:
        if observation.external_reference is None:
            return
        if connection.execute(
            "SELECT 1 FROM mcp_delivery_observations WHERE external_reference=? AND action_id!=? "
            "UNION SELECT 1 FROM mcp_delivery_reconciliations "
            "WHERE external_reference=? AND action_id!=?",
            (
                observation.external_reference,
                observation.action_id,
                observation.external_reference,
                observation.action_id,
            ),
        ).fetchone():
            raise ContractValidationError("External delivery operation was already recorded.")

    def _recover_receipt(
        self,
        connection: sqlite3.Connection,
        request: McpCallReconciliation,
        *,
        now: datetime,
    ) -> McpCallReceipt:
        """Record the recovery observation now, without inventing a past result."""
        original, admitted_at = self._call(connection, request.call_id)
        run = self._run(connection, original.run_id)
        if self._closed(connection, run.run_id) or request.observed_at < admitted_at:
            raise ContractValidationError("Recovery needs an unresolved chronological call.")
        dispatch = connection.execute(
            "SELECT dispatched_at FROM mcp_dispatches WHERE call_id=?",
            (request.call_id,),
        ).fetchone()
        at = datetime.fromisoformat(dispatch[0]) if dispatch else None
        if at is not None and request.observed_at < at:
            raise ContractValidationError("Readback cannot predate the actual dispatch.")
        if at is None and (request.result.status != "failed" or not request.positive_readback):
            raise ContractValidationError(
                "An undispatched intent can only be closed as positively checked not-called.",
            )
        result = McpProviderResult(
            status="unknown" if at else "failed",
            reason="recovered_dispatch_without_response" if at else "recovered_without_dispatch",
        )
        if at is not None:
            self._halt(connection, run.source, "unknown", at, now)
        receipt = McpCallReceipt(
            call_id=request.call_id,
            run_id=run.run_id,
            batch_id=original.batch_id,
            operation=original.operation,
            admitted_at=admitted_at,
            dispatched_at=at,
            completed_at=now,
            dispatched=at is not None,
            status="unknown" if at else "not_called",
            result=result,
            budget=self._budget(connection, run),
        )
        connection.execute(
            "INSERT INTO mcp_results VALUES (?,?,?)",
            (
                request.call_id,
                canonical_digest(result.model_dump(mode="json")),
                receipt.model_dump_json(),
            ),
        )
        return receipt

    def reconcile(
        self,
        request: McpCallReconciliation,
        *,
        now: datetime,
    ) -> McpCallReceipt:
        request = McpCallReconciliation.model_validate(request.model_dump(mode="json"))
        if now.tzinfo is None or request.observed_at > now:
            raise ContractValidationError("MCP readback needs actual chronological evidence.")
        with self._write() as connection:
            prior = connection.execute(
                "SELECT reconciliation_json,receipt_json FROM mcp_reconciliations WHERE call_id=?",
                (request.call_id,),
            ).fetchone()
            if prior:
                if McpCallReconciliation.model_validate_json(prior[0]) != request:
                    raise ContractValidationError(
                        "MCP call already has a different reconciliation."
                    )
                return McpCallReceipt.model_validate_json(prior[1])
            old = self._receipt(connection, request.call_id)
            if old is None:
                old = self._recover_receipt(connection, request, now=now)
                if not old.dispatched:
                    receipt = old.model_copy(update={"result": request.result})
                    connection.execute(
                        "INSERT INTO mcp_reconciliations VALUES (?,?,?)",
                        (
                            request.call_id,
                            request.model_dump_json(),
                            receipt.model_dump_json(),
                        ),
                    )
                    return receipt
            if old is None or old.status != "unknown" or old.dispatched_at is None:
                raise ContractValidationError("Only an actual unknown MCP call can be reconciled.")
            if now.tzinfo is None or not old.dispatched_at <= request.observed_at <= now:
                raise ContractValidationError("MCP readback needs actual chronological evidence.")
            run = self._run(connection, old.run_id)
            result = request.result
            if result.error_code == "429001":
                result = result.model_copy(update={"status": "gate"})
            selection = None
            if old.operation == "search" and result.status == "success":
                if result.listings is None or not result.loaded:
                    raise ContractValidationError("MCP search readback needs loaded real listings.")
                dispatch = connection.execute(
                    "SELECT sourcing_attempt_id FROM mcp_dispatches WHERE call_id=?",
                    (old.call_id,),
                ).fetchone()
                selection = SqliteQueryRepository(self.database).take_in(
                    connection,
                    SourcingQueryCapture(
                        attempt_id=dispatch[0],
                        items=result.listings,
                        loaded=True,
                        access_state="authenticated",
                        next_cursor=result.next_cursor,
                    ),
                    now=request.observed_at,
                )
                result = result.model_copy(update={"payload": None, "listings": selection.items})
            if result.status in {"gate", "already_applied", "blocked"}:
                self._halt(connection, run.source, result.status, old.dispatched_at, now)
            receipt = McpCallReceipt.model_validate(
                old.model_dump(mode="json")
                | {
                    "result": result.model_dump(mode="json"),
                    "status": result.status,
                    "completed_at": now,
                    "selection": selection,
                    "budget": self._budget(connection, run),
                }
            )
            connection.execute(
                "INSERT INTO mcp_reconciliations VALUES (?,?,?)",
                (
                    old.call_id,
                    request.model_dump_json(),
                    receipt.model_dump_json(),
                ),
            )
            return receipt

    def reconcile_delivery(
        self,
        observation: McpDeliveryObservation,
        *,
        now: datetime,
    ) -> McpDeliveryObservation:
        observation = McpDeliveryObservation.model_validate(observation.model_dump(mode="json"))
        with self._write() as connection:
            old = connection.execute(
                "SELECT observation_json FROM mcp_delivery_observations WHERE action_id=?",
                (observation.action_id,),
            ).fetchone()
            if old is None:
                raise ContractValidationError(
                    "Delivery reconciliation needs an unknown observation."
                )
            original = McpDeliveryObservation.model_validate_json(old[0])
            prior = connection.execute(
                "SELECT observation_json FROM mcp_delivery_reconciliations WHERE action_id=?",
                (observation.action_id,),
            ).fetchone()
            if prior:
                if McpDeliveryObservation.model_validate_json(prior[0]) != observation:
                    raise ContractValidationError("Delivery already has different reconciliation.")
                return observation
            if (
                original.status != "unknown"
                or observation.status == "unknown"
                or observation.run_id != original.run_id
                or observation.source_job_id != original.source_job_id
                or observation.occurred_at != original.occurred_at
                or now.tzinfo is None
                or not original.observed_at <= observation.observed_at <= now
            ):
                raise ContractValidationError(
                    "Delivery reconciliation changed identity or chronology."
                )
            run = self._run(connection, original.run_id)
            if self._closed(connection, run.run_id):
                raise ContractValidationError("Closed MCP delivery facts are frozen.")
            self._unique_delivery(connection, observation)
            if observation.status in {"blocked", "already_applied", "gate"}:
                self._halt(connection, run.source, observation.status, observation.observed_at, now)
            connection.execute(
                "INSERT INTO mcp_delivery_reconciliations VALUES (?,?,?)",
                (
                    observation.action_id,
                    observation.external_reference,
                    observation.model_dump_json(),
                ),
            )
            return observation
