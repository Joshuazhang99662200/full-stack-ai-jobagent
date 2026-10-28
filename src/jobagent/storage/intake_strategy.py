"""Versioned domain learning and frozen next-round claims for manual intake."""

import json
import sqlite3
from datetime import datetime

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.lexicon import serialize_lexicon
from jobagent.jobs.query_derivation import SearchQueryDeriver
from jobagent.jobs.search_learning import rebuild_lexicon
from jobagent.jobs.sourcing import SOURCING_DAY
from jobagent.schemas.job_intake import (
    IntakeClaim,
    IntakeLegacyScope,
    IntakeSearchRecord,
    IntakeStrategyInput,
)
from jobagent.schemas.job_intelligence import SearchRun
from jobagent.schemas.lexicon import CombinationPlan, CombinationRequest, Lexicon
from jobagent.schemas.search_learning import SearchLearningRequest
from jobagent.schemas.sourcing import SourcingAttempt, SourcingResult
from jobagent.storage.database import Database
from jobagent.storage.job_intake_service import JobIntakeService
from jobagent.storage.sourcing_repository import SqliteSourcingRepository


class IntakeStrategyService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.service = JobIntakeService(database)
        self.repository = self.service.repository
        self.knowledge = self.service.knowledge

    @staticmethod
    def history_digest(connection: sqlite3.Connection) -> str:
        rows = connection.execute(
            "SELECT * FROM job_searches ORDER BY searched_at, source, search_term",
        ).fetchall()
        return canonical_digest(
            [
                SearchRun(
                    source=row["source"],
                    search_term=row["search_term"],
                    searched_at=datetime.fromisoformat(row["searched_at"]),
                    results=row["results"],
                    new=row["new"],
                ).model_dump(mode="json")
                for row in rows
            ]
        )

    @staticmethod
    def check_external(connection: sqlite3.Connection, result: dict[str, object]) -> None:
        scope = IntakeLegacyScope.model_validate(
            {
                "external_snapshot_ids": result.get("external_snapshot_ids", []),
                "historical_signals": result.get("historical_signals", []),
            }
        )
        for snapshot_id in scope.external_snapshot_ids:
            latest = connection.execute(
                "SELECT snapshot_id FROM jd_snapshots WHERE job_id = "
                "(SELECT job_id FROM jd_snapshots WHERE snapshot_id = ?) "
                "ORDER BY snapshot_version DESC LIMIT 1",
                (snapshot_id,),
            ).fetchone()
            if latest is None or latest["snapshot_id"] != snapshot_id:
                reject("A retained domain snapshot changed; refresh its features and strategy.")

    def active(
        self, candidate_id: str, domain: str, source: str, *, require_current: bool = False
    ) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT strategy_json, source_digest FROM intake_active_strategies "
                "WHERE candidate_id = ? AND domain = ? AND source = ?",
                (candidate_id, domain, source),
            ).fetchone()
        if row is None:
            reject("No active strategy for this candidate, domain and source.")
        assert row is not None
        records = self.repository.list_records(candidate_id, domain)
        if require_current:
            with self.database.connect() as connection:
                self.check_external(connection, json.loads(row["strategy_json"]))
            with self.database.connect() as connection:
                if (
                    self.history_digest(connection)
                    != json.loads(row["strategy_json"])["history_digest"]
                ):
                    reject("Search history changed; refresh the active strategy.")
            if self.repository.source_digest(records) != row["source_digest"]:
                reject("Domain inputs changed; refresh strategy before the next round.")
            for record in records:
                if record.feature_set_id and not record.closed and not record.merged_into:
                    self.service.bound(record)
        value: dict[str, object] = json.loads(row["strategy_json"])
        return value

    @staticmethod
    def policy_settings(policy: Lexicon) -> str:
        return canonical_digest(
            {
                "domain": policy.domain,
                "combinations": policy.combinations,
                "terms": [
                    t.model_dump(
                        mode="json",
                        exclude={
                            "count",
                            "last_seen",
                            "source_refs",
                            "preference_weight",
                            "independent_companies",
                            "maturity",
                        },
                    )
                    for t in policy.terms
                ],
            }
        )

    def rebuild(
        self, data: dict[str, object], policy: Lexicon, *, now: datetime
    ) -> dict[str, object]:
        request = IntakeStrategyInput.model_validate(data)
        if request.domain != policy.domain or now.tzinfo is None:
            reject("Domain policy and timezone-aware clock are required.")
        for record in self.repository.list_records(request.candidate_id, request.domain):
            self.service.synchronize(record.intake_id, request.candidate_id, now=now)
        records = self.repository.list_records(request.candidate_id, request.domain)
        source_digest = self.repository.source_digest(records)
        selected = [r for r in records if r.feature_set_id and not r.closed and not r.merged_into]
        features = []
        for record in selected:
            self.service.bound(record)
            feature_set = self.service.features(record.feature_set_id or "")
            if feature_set.snapshot_id != record.snapshot_id:
                reject("Intake features differ from its current snapshot.")
            features.append(feature_set)
        signal_ids = {r.signal_id for r in selected if r.signal_id}
        with self.database.connect() as connection:
            old = connection.execute(
                "SELECT strategy_json FROM intake_active_strategies "
                "WHERE candidate_id = ? AND domain = ? AND source = ?",
                (request.candidate_id, request.domain, request.source),
            ).fetchone()
        old_result = json.loads(old["strategy_json"]) if old else {}
        legacy = IntakeLegacyScope.model_validate(
            {
                "external_snapshot_ids": old_result.get("external_snapshot_ids", []),
                "historical_signals": old_result.get("historical_signals", []),
            }
        )
        queued_jobs = {r.job_id for r in records if r.job_id}
        external_ids = (
            set(legacy.external_snapshot_ids) | set(request.snapshot_ids) | set(policy.snapshot_ids)
        )
        external_features = {}
        for snapshot_id in sorted(external_ids):
            original = self.knowledge.get(snapshot_id)
            if original.job_id in queued_jobs:
                continue
            latest = self.knowledge.list_snapshots(original.job_id)[-1]
            values = self.knowledge.feature_sets([latest.snapshot_id])
            if latest.completeness != "full" or len(values) != 1:
                reject("Retained domain snapshots need current full text and persisted features.")
            external_features[latest.snapshot_id] = values[0]
        features.extend(external_features.values())
        historical = {s.event_id: s for s in legacy.historical_signals}
        if request.historical_learning is not None:
            if request.historical_learning.candidate_id != request.candidate_id:
                reject("Historical feedback belongs to another candidate.")
            for event in request.historical_learning.signals:
                if event.event_id in historical and historical[event.event_id] != event:
                    reject("Historical feedback IDs cannot change their original content.")
                historical[event.event_id] = event
        learning = SearchLearningRequest(
            candidate_id=request.candidate_id,
            baseline_queries=request.baseline_queries,
            signals=[
                *historical.values(),
                *[
                    s
                    for s in self.repository.signals(request.candidate_id, request.domain)
                    if s.event_id in signal_ids
                ],
            ],
        )
        policy_settings = self.policy_settings(policy)
        if old:
            old_active = json.loads(old["strategy_json"])
            previous = Lexicon.model_validate(json.loads(old["strategy_json"])["lexicon"])
            if (
                self.policy_settings(previous) == policy_settings
                or old_active.get("policy_settings") == policy_settings
            ):
                policy = previous
                policy_settings = old_active.get("policy_settings", policy_settings)
            elif int(policy.lexicon_version[1:]) < int(previous.lexicon_version[1:]):
                policy = policy.model_copy(update={"lexicon_version": previous.lexicon_version})
        updated = rebuild_lexicon(policy, features, learning)
        combination_request = CombinationRequest(
            candidate_id=request.candidate_id,
            source=request.source,
            baseline_queries=request.baseline_queries,
            query_limit=request.query_limit,
            now=now,
            learning=learning,
            feature_sets=features,
            history=self.service.jobs.searches(),
        )
        plan = SearchQueryDeriver().derive_combinations(updated.lexicon, combination_request)
        self.knowledge.save_lexicon(request.candidate_id, policy)
        self.knowledge.save_lexicon(request.candidate_id, updated.lexicon)
        self.knowledge.save_plan(updated.lexicon, combination_request, plan)
        result: dict[str, object] = {
            "version_digest": updated.version_digest,
            "lexicon": updated.lexicon.model_dump(mode="json"),
            "markdown": serialize_lexicon(updated.lexicon),
            "plan": plan.model_dump(mode="json"),
            "input": {"request": combination_request.model_dump(mode="json")},
            "source_digest": source_digest,
            "external_snapshot_ids": sorted(external_features),
            "historical_signals": [s.model_dump(mode="json") for s in historical.values()],
            "policy_settings": policy_settings,
            "activated_at": now.isoformat(),
            "history_digest": canonical_digest(
                [h.model_dump(mode="json") for h in combination_request.history]
            ),
        }
        self.activate(
            request,
            result,
            source_digest,
            now=now,
            expected_active_digest=canonical_digest(old_result) if old else None,
        )
        return result

    def activate(
        self,
        request: IntakeStrategyInput,
        result: dict[str, object],
        source_digest: str,
        *,
        now: datetime,
        expected_active_digest: str | None = None,
    ) -> None:
        plan = CombinationPlan.model_validate(result["plan"])
        with self.repository.write() as connection:
            active_row = connection.execute(
                "SELECT strategy_json FROM intake_active_strategies "
                "WHERE candidate_id = ? AND domain = ? AND source = ?",
                (request.candidate_id, request.domain, request.source),
            ).fetchone()
            actual_digest = (
                canonical_digest(json.loads(active_row["strategy_json"])) if active_row else None
            )
            if actual_digest != expected_active_digest:
                reject("Active policy changed during learning; old outputs were not activated.")
            self.check_external(connection, result)
            if self.history_digest(connection) != result["history_digest"]:
                reject("Search history changed during learning; outputs were not activated.")
            records = self.repository.scoped(connection, request.candidate_id, request.domain)
            if self.repository.source_digest(records) != source_digest:
                reject("Intake changed during learning; immutable outputs were not activated.")
            for record in records:
                if not record.feature_set_id or record.closed or record.merged_into:
                    continue
                latest = connection.execute(
                    "SELECT snapshot_id FROM jd_snapshots WHERE job_id = ? "
                    "ORDER BY snapshot_version DESC LIMIT 1",
                    (record.job_id,),
                ).fetchone()
                if latest is None or latest["snapshot_id"] != record.snapshot_id:
                    reject("JD changed during strategy generation; no activation performed.")
                if record.platform != request.source:
                    continue
                chosen = any(record.snapshot_id in q.snapshot_ids for q in plan.ordered_queries)
                deferred = any(record.snapshot_id in q.snapshot_ids for q in plan.deferred_queries)
                status = "selected" if chosen else "deferred" if deferred else "candidate"
                if record.plan_id == plan.version and record.strategy_status == status:
                    continue
                updated = record.model_copy(
                    update={
                        "plan_id": plan.version,
                        "lexicon_digest": result["version_digest"],
                        "strategy_status": status,
                        "version": record.version + 1,
                        "updated_at": now,
                    }
                )
                self.repository.append(
                    connection,
                    updated,
                    "STRATEGY_"
                    + canonical_digest([record.intake_id, record.version, plan.version])[7:],
                    "strategy_activated",
                    source_digest,
                )
            connection.execute(
                "INSERT INTO intake_active_strategies VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(candidate_id, domain, source) DO UPDATE SET "
                "source_digest=excluded.source_digest, strategy_json=excluded.strategy_json",
                (
                    request.candidate_id,
                    request.domain,
                    request.source,
                    source_digest,
                    json.dumps(result, ensure_ascii=False),
                ),
            )

    def claim(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = IntakeClaim.model_validate(data)
        run = SqliteSourcingRepository(self.database).get_run(request.run_id)
        if (
            run.candidate_id != request.candidate_id
            or now.tzinfo is None
            or run.opened_at.astimezone(SOURCING_DAY).date() != now.astimezone(SOURCING_DAY).date()
        ):
            reject("A current sourcing round for this candidate is required.")
        with self.repository.write() as connection:
            previous = connection.execute(
                "SELECT * FROM intake_strategy_claims WHERE run_id = ?",
                (request.run_id,),
            ).fetchone()
            if previous:
                if (
                    previous["candidate_id"] != request.candidate_id
                    or previous["domain"] != request.domain
                ):
                    reject("This round is claimed by another scope.")
                replay: dict[str, object] = json.loads(previous["claim_json"])
                return replay
            row = connection.execute(
                "SELECT strategy_json, source_digest FROM intake_active_strategies "
                "WHERE candidate_id = ? AND domain = ? AND source = ?",
                (request.candidate_id, request.domain, run.source),
            ).fetchone()
            if row is None:
                reject("Generate a current active strategy before claiming the next round.")
            assert row is not None
            records = self.repository.scoped(connection, request.candidate_id, request.domain)
            if self.repository.source_digest(records) != row["source_digest"]:
                reject("Strategy inputs changed; refresh before claiming.")
            for record in records:
                if record.feature_set_id and not record.closed and not record.merged_into:
                    latest = connection.execute(
                        "SELECT snapshot_id FROM jd_snapshots WHERE job_id = ? "
                        "ORDER BY snapshot_version DESC LIMIT 1",
                        (record.job_id,),
                    ).fetchone()
                    if latest is None or latest["snapshot_id"] != record.snapshot_id:
                        reject("JD changed; synchronize and refresh strategy.")
            active = json.loads(row["strategy_json"])
            self.check_external(connection, active)
            if self.history_digest(connection) != active["history_digest"]:
                reject("Search history changed; refresh strategy before the next round.")
            plan = CombinationPlan.model_validate(active["plan"])
            if len(plan.ordered_queries or plan.fallback_queries) > run.query_limit:
                reject("Plan exceeds this round's frozen query budget; rebuild with its limit.")
            result: dict[str, object] = {
                "candidate_id": request.candidate_id,
                "domain": request.domain,
                "source": run.source,
                "run_id": run.run_id,
                "claimed_at": now.isoformat(),
                "plan": plan.model_dump(mode="json"),
                "version_digest": active["version_digest"],
                "grants_delivery_permission": False,
            }
            connection.execute(
                "INSERT INTO intake_strategy_claims VALUES (?, ?, ?, ?)",
                (
                    run.run_id,
                    request.candidate_id,
                    request.domain,
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            return result

    def record_search(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = IntakeSearchRecord.model_validate(data)
        with self.repository.write() as connection:
            claim = connection.execute(
                "SELECT * FROM intake_strategy_claims WHERE run_id = ?",
                (request.run_id,),
            ).fetchone()
            if (
                claim is None
                or claim["candidate_id"] != request.candidate_id
                or claim["domain"] != request.domain
            ):
                reject("A matching frozen strategy claim is required.")
            assert claim is not None
            bound = json.loads(claim["claim_json"])
            plan = CombinationPlan.model_validate(bound["plan"])
            prior = connection.execute(
                "SELECT execution_json FROM intake_search_executions WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            if prior:
                replay: dict[str, object] = json.loads(prior["execution_json"])
                if replay["run_id"] != request.run_id or replay["new_count"] != request.new_count:
                    reject("Search attempt belongs to another round.")
                return replay
            attempt_row = connection.execute(
                "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            result_row = connection.execute(
                "SELECT result_json FROM sourcing_results WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            if attempt_row is None or result_row is None:
                reject("Search execution needs an actual completed query observation.")
            assert attempt_row is not None and result_row is not None
            attempt = SourcingAttempt.model_validate_json(attempt_row["attempt_json"])
            result = SourcingResult.model_validate_json(result_row["result_json"])
            queries = [q.query for q in plan.ordered_queries] or plan.fallback_queries
            if not (
                attempt.run_id == request.run_id
                and attempt.kind == "query"
                and attempt.source == bound["source"]
                and attempt.search_term in queries
                and result.outcome == "complete"
                and result.listing_count is not None
                and request.new_count <= result.listing_count
                and datetime.fromisoformat(bound["claimed_at"])
                <= attempt.occurred_at
                <= result.completed_at
                <= now
            ):
                reject("The completed attempt is not an executed query from this claimed plan.")
            execution: dict[str, object] = {
                "attempt_id": request.attempt_id,
                "run_id": request.run_id,
                "candidate_id": request.candidate_id,
                "domain": request.domain,
                "source": attempt.source,
                "query": attempt.search_term,
                "plan_id": plan.version,
                "listing_count": result.listing_count,
                "new_count": request.new_count,
                "completed_at": result.completed_at.isoformat(),
            }
            connection.execute(
                "INSERT INTO intake_search_executions VALUES (?, ?, ?)",
                (
                    request.attempt_id,
                    request.run_id,
                    json.dumps(execution, ensure_ascii=False),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO job_searches VALUES (?, ?, ?, ?, ?)",
                (
                    attempt.source,
                    attempt.search_term,
                    attempt.occurred_at.isoformat(),
                    result.listing_count,
                    request.new_count,
                ),
            )
            return execution
