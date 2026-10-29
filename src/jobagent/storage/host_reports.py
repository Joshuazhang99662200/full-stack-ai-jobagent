"""Immutable round evidence reports; synthetic success never proves live browser integration."""

import json
from collections import Counter
from datetime import datetime
from typing import get_args

from pydantic import ValidationError

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.pipeline import silence_deadline
from jobagent.schemas.host_checks import HostQueryExecution, HostRoundInput, HostTwoRoundInput
from jobagent.schemas.jd_snapshot import SnapshotDiscovery
from jobagent.schemas.job_intake import IntakeHistory, IntakeRecord
from jobagent.schemas.lexicon import CombinationPlan
from jobagent.schemas.pipeline import PipelineJob, PipelineMeta, PipelineState
from jobagent.schemas.sourcing import SourcingAttempt, SourcingResult
from jobagent.storage.database import Database
from jobagent.storage.host_checks import HostPageService
from jobagent.storage.pipeline_repository import Pair, PipelineRepository
from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository
from jobagent.storage.sourcing_repository import SqliteSourcingRepository


class HostRoundReporter:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, report_id: str, candidate_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM host_round_reports "
                "WHERE report_id = ? AND candidate_id = ?",
                (report_id, candidate_id),
            ).fetchone()
        if row is None:
            reject("Round report not found for this candidate.")
        result: dict[str, object] = json.loads(row["report_json"])
        return result

    def record(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = HostRoundInput.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        if request.completed_at > now:
            reject("Round reports cannot claim future completion.")
        with self.database.connect() as connection:
            old = connection.execute(
                "SELECT * FROM host_round_reports WHERE report_id = ?",
                (request.report_id,),
            ).fetchone()
        if old:
            if old["input_digest"] != digest or old["candidate_id"] != request.candidate_id:
                reject("A report ID cannot change its original evidence.")
            replay: dict[str, object] = json.loads(old["report_json"])
            return replay
        sources = set()
        plans = []
        executions: list[HostQueryExecution] = []
        lexicon_versions = []
        attempts = []
        meter = SqliteSourcingRepository(self.database)
        with self.database.connect() as connection:
            for run_id in request.run_ids:
                run = meter.get_run(run_id)
                if (
                    run.candidate_id != request.candidate_id
                    or not request.started_at <= run.opened_at <= request.completed_at
                ):
                    reject("Each report run must belong to this candidate and time window.")
                sources.add(run.source)
                claim = connection.execute(
                    "SELECT * FROM intake_strategy_claims WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if claim is None or claim["domain"] != request.domain:
                    reject("Round reports require actual frozen strategy claims.")
                claim_body = json.loads(claim["claim_json"])
                plan = CombinationPlan.model_validate(claim_body["plan"])
                plans.append(
                    {"run_id": run_id, "source": run.source, "plan": plan.model_dump(mode="json")}
                )
                lexicon_versions.append(claim_body["version_digest"])
                for row in connection.execute(
                    "SELECT attempt_json FROM sourcing_attempts WHERE run_id = ?",
                    (run_id,),
                ).fetchall():
                    attempt = SourcingAttempt.model_validate_json(row["attempt_json"])
                    if attempt.occurred_at <= request.completed_at:
                        attempts.append(attempt)
                for saved in connection.execute(
                    "SELECT execution_json FROM intake_search_executions WHERE run_id = ?",
                    (run_id,),
                ).fetchall():
                    execution = HostQueryExecution.model_validate_json(saved["execution_json"])
                    if execution.completed_at <= request.completed_at:
                        executions.append(execution)
            observed_search_ids = set(request.search_observation_ids)
            for saved in connection.execute(
                "SELECT d.discovery_json, s.snapshot_json FROM jd_discoveries d "
                "JOIN jd_snapshots s ON s.snapshot_id = d.snapshot_id",
            ).fetchall():
                discovery = SnapshotDiscovery.model_validate_json(saved["discovery_json"])
                platform = json.loads(saved["snapshot_json"])["platform"]
                if (
                    platform in sources
                    and request.started_at <= discovery.fetched_at <= request.completed_at
                    and discovery.discovery_kind not in {"manual", "recommendation"}
                ):
                    observed_search_ids.add(discovery.observation_id)
            executed_queries = {(e.source, e.query) for e in executions}
            unattributed = []
            for observation_id in sorted(observed_search_ids):
                row = connection.execute(
                    "SELECT discovery_json FROM jd_discoveries WHERE observation_id = ?",
                    (observation_id,),
                ).fetchone()
                if row is None:
                    unattributed.append(observation_id)
                    continue
                observation = SnapshotDiscovery.model_validate_json(row["discovery_json"])
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM jd_snapshots WHERE snapshot_id = ?",
                    (observation.snapshot_id,),
                ).fetchone()
                platform = json.loads(snapshot["snapshot_json"])["platform"] if snapshot else None
                if (
                    observation.discovery_kind != "search"
                    or not observation.query_hit
                    or (platform, observation.query_hit) not in executed_queries
                    or not request.started_at <= observation.fetched_at <= request.completed_at
                ):
                    unattributed.append(observation_id)
            for observation_id in request.manual_observation_ids:
                row = connection.execute(
                    "SELECT discovery_json FROM jd_discoveries WHERE observation_id = ?",
                    (observation_id,),
                ).fetchone()
                if row is None or SnapshotDiscovery.model_validate_json(
                    row["discovery_json"]
                ).discovery_kind not in {
                    "manual",
                    "recommendation",
                }:
                    reject("Manual attribution must reference actual non-search discoveries.")
            drafts = set()
            intakes_as_of: dict[str, IntakeRecord] = {}
            for row in connection.execute("SELECT event_json FROM intake_events").fetchall():
                history = IntakeHistory.model_validate_json(row["event_json"])
                state = history.state
                if (
                    state.candidate_id == request.candidate_id
                    and state.domain == request.domain
                    and state.updated_at <= request.completed_at
                ):
                    previous = intakes_as_of.get(state.intake_id)
                    if previous is None or state.version > previous.version:
                        intakes_as_of[state.intake_id] = state
                if (
                    history.kind == "draft"
                    and history.state.candidate_id == request.candidate_id
                    and request.started_at <= history.state.updated_at <= request.completed_at
                ):
                    drafts.add(history.state.job_id)
            partial = [
                state.intake_id
                for state in intakes_as_of.values()
                if state.snapshot_id is None and not state.closed and not state.merged_into
            ]
            pending = connection.execute(
                "SELECT COUNT(*) FROM host_legacy_rows r JOIN host_migration_runs m "
                "ON m.migration_id = r.migration_id WHERE m.candidate_id = ? "
                "AND r.tracking_proof_status = 'proof_pending'",
                (request.candidate_id,),
            ).fetchone()[0]
        pipeline_summary = self._pipeline_summary(request)
        if pipeline_summary is not None:
            tracking = pipeline_summary
            pipeline_partial = pipeline_summary["partial_not_in_strategy"]
            assert isinstance(pipeline_partial, list)
            partial = sorted(set(partial) | set(pipeline_partial))
        else:
            tracking_repository = SqliteSentTrackingRepository(self.database)
            records = []
            for current in tracking_repository.list_records(request.candidate_id):
                tracking_history = [
                    event
                    for event in tracking_repository.history(
                        current.tracking_id,
                        request.candidate_id,
                    )
                    if event.occurred_at <= request.completed_at
                ]
                if tracking_history:
                    records.append(tracking_history[-1].state)
            closed = [
                r
                for r in records
                if r.abandoned_at is not None
                and request.started_at <= r.abandoned_at <= request.completed_at
            ]
            tracking = {
                "counts": dict(Counter(r.tracking_state.value for r in records)),
                "proof_pending": pending,
                "next_checks": [
                    {
                        "tracking_id": r.tracking_id,
                        "source": r.platform,
                        "next_check_at": r.next_check_at.isoformat() if r.next_check_at else None,
                        "check_count": r.check_count,
                        "missed_check_days": r.missed_check_days,
                        "paused": r.paused,
                    }
                    for r in records
                ],
                "newly_closed": len(closed),
                "closure_reasons": dict(Counter(r.abandon_reason for r in closed)),
            }
        pages = HostPageService(self.database).latest(request.candidate_id, at=request.completed_at)
        login_states = {key: value for key, value in pages.items() if key.split("/")[0] in sources}
        settled = all(
            source + "/" + surface in login_states
            and login_states[source + "/" + surface]["state"] == "logged_in"
            and datetime.fromisoformat(str(login_states[source + "/" + surface]["observed_at"]))
            >= request.started_at
            for source in sources
            for surface in ("messages", "search")
        )
        search_attempts = [a for a in attempts if a.kind == "query"]
        executed_ids = {e.attempt_id for e in executions}
        unexecuted = [a.attempt_id for a in search_attempts if a.attempt_id not in executed_ids]
        denominator = len(observed_search_ids)
        ratio = (denominator - len(unattributed)) / denominator if denominator else None
        core_ok = bool(
            executions
            and denominator
            and not unattributed
            and not unexecuted
            and request.dedup_count is not None
            and request.filter_reasons is not None
            and settled
            and (
                pipeline_summary is None
                or pipeline_summary["as_of_verification"] == "immutable_request_snapshots"
            )
        )
        details = [a for a in attempts if a.kind == "detail"]
        outcomes: Counter[str] = Counter()
        with self.database.connect() as connection:
            for attempt in details:
                saved_result = connection.execute(
                    "SELECT result_json FROM sourcing_results WHERE attempt_id = ?",
                    (attempt.attempt_id,),
                ).fetchone()
                outcome = (
                    SourcingResult.model_validate_json(saved_result[0]) if saved_result else None
                )
                if outcome is None or outcome.completed_at > request.completed_at:
                    outcomes["pending"] += 1
                elif outcome.outcome in {"complete", "partial"}:
                    outcomes[outcome.outcome] += 1
                else:
                    outcomes["failed"] += 1
        report: dict[str, object] = {
            "report_id": request.report_id,
            "candidate_id": request.candidate_id,
            "domain": request.domain,
            "started_at": request.started_at.isoformat(),
            "completed_at": request.completed_at.isoformat(),
            "plans": plans,
            "detail_reads": {
                "attempts": len(details),
                **{key: outcomes[key] for key in ("complete", "partial", "failed", "pending")},
            },
            "executed_queries": [e.model_dump(mode="json") for e in executions],
            "unexecuted_query_attempts": unexecuted,
            "query_attribution": {
                "ratio": ratio,
                "search_samples": denominator,
                "manual_samples": len(request.manual_observation_ids),
                "unattributed": unattributed,
            },
            "dedup_count": request.dedup_count,
            "filter_reasons": request.filter_reasons,
            "host_metrics_evidence": request.metrics_evidence_reference,
            "host_metrics_verification": "host_observed_only"
            if request.metrics_evidence_reference
            else "unverified",
            "new_jobs": sum(e.new_count for e in executions),
            "new_drafts": len(drafts),
            "lexicon_versions": sorted(set(lexicon_versions)),
            "tracking": tracking,
            "pipeline": pipeline_summary,
            "login_states": login_states,
            "partial_not_in_strategy": partial,
            "unfinished": request.unfinished,
            "evidence_mode": request.evidence_mode,
            "host_evidence_reference": request.host_evidence_reference,
            "core_checks_passed": core_ok,
            "real_browser_verified": False,
        }
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO host_round_reports VALUES (?, ?, ?, ?)",
                (
                    request.report_id,
                    request.candidate_id,
                    digest,
                    json.dumps(report, ensure_ascii=False),
                ),
            )
        return report

    def _pipeline_summary(self, request: HostRoundInput) -> dict[str, object] | None:
        """Read immutable response snapshots, never project later state into an old round."""
        with self.database.connect() as connection:
            authority = connection.execute(
                "SELECT activated_at FROM pipeline_authorities WHERE candidate_id = ?",
                (request.candidate_id,),
            ).fetchone()
            if authority is None or datetime.fromisoformat(authority[0]) > request.completed_at:
                return None
            rows = connection.execute(
                "SELECT pipeline_id,response_json FROM pipeline_requests "
                "WHERE candidate_id = ? ORDER BY rowid",
                (request.candidate_id,),
            ).fetchall()
        snapshots: dict[str, Pair] = {}
        invalid = set()
        for row in rows:
            try:
                payload = json.loads(row["response_json"])
                job = PipelineJob.model_validate(payload["job"])
                meta = PipelineMeta.model_validate(payload["meta"])
            except (ValidationError, KeyError, TypeError, ValueError):
                invalid.add(row["pipeline_id"])
                continue
            if (
                job.candidate_id != request.candidate_id
                or job.pipeline_id != row["pipeline_id"]
                or meta.pipeline_id != job.pipeline_id
            ):
                invalid.add(row["pipeline_id"])
                continue
            if job.updated_at > request.completed_at or job.entered_at > request.completed_at:
                continue
            old = snapshots.get(job.pipeline_id)
            if old is None or meta.version >= old[1].version:
                snapshots[job.pipeline_id] = (job, meta)
        repository = PipelineRepository(self.database)
        for current, metadata in repository.list_records(request.candidate_id):
            if current.entered_at > request.completed_at:
                continue
            saved = snapshots.get(current.pipeline_id)
            history = [
                entry
                for entry in repository.history(current.pipeline_id, request.candidate_id)
                if entry.changed_at <= request.completed_at
            ]
            latest = (
                max(enumerate(history), key=lambda item: (item[1].changed_at, item[0]))[1]
                if history
                else None
            )
            if (
                saved is None
                or latest is None
                or latest.to_state != saved[0].pipeline_state
                or latest.changed_at != saved[0].state_changed_at
                or (
                    current.updated_at <= request.completed_at
                    and metadata.version != saved[1].version
                )
            ):
                invalid.add(current.pipeline_id)
        verified = [pair for key, pair in sorted(snapshots.items()) if key not in invalid]
        counts = {state: 0 for state in get_args(PipelineState)}
        for job, _ in verified:
            counts[job.pipeline_state] += 1
        closed = [
            (job, meta)
            for job, meta in verified
            if job.pipeline_state == "abandoned"
            and request.started_at
            <= (meta.abandoned_at or job.state_changed_at)
            <= request.completed_at
        ]
        checks = []
        next_poll = request.next_poll_at
        for job, meta in verified:
            if job.pipeline_state in {"abandoned", "interviewed"}:
                continue
            deadline = silence_deadline(job, meta.model_copy(update={"paused": False}))
            eligible = deadline is not None and not meta.paused
            checks.append(
                {
                    "pipeline_id": job.pipeline_id,
                    "source": job.platform,
                    "domain": meta.domain,
                    "pipeline_state": job.pipeline_state,
                    "proof_status": meta.proof_status,
                    "version": meta.version,
                    "paused": meta.paused,
                    "last_checked_at": meta.last_checked_at.isoformat()
                    if meta.last_checked_at
                    else None,
                    "deadline_at": deadline.isoformat() if deadline else None,
                    "expiry_due": bool(
                        eligible and deadline is not None and deadline <= request.completed_at
                    ),
                    "next_check_at": next_poll.isoformat()
                    if next_poll is not None and eligible
                    else None,
                    "next_check_policy": "host_next_poll",
                    "schedule_verification": "host_observed_only"
                    if next_poll is not None
                    else "unverified",
                }
            )
        partial = [
            job.pipeline_id
            for job, meta in verified
            if meta.domain == request.domain and (job.jd_text is None or meta.snapshot_id is None)
        ]
        return {
            "state_authority": "pipeline_jobs",
            "scope": "candidate",
            "as_of": request.completed_at.isoformat(),
            "counts": counts,
            "proof_pending": sum(meta.proof_status == "proof_pending" for _, meta in verified),
            "next_checks": checks,
            "newly_closed": len(closed),
            "newly_abandoned": len(closed),
            "closure_reasons": dict(Counter(job.state_reason for job, _ in closed)),
            "partial_not_in_strategy": sorted(partial),
            "unverified_pipeline_ids": sorted(invalid),
            "as_of_verification": "incomplete_snapshot_history"
            if invalid
            else "immutable_request_snapshots",
        }

    def verify_two(self, data: dict[str, object]) -> dict[str, object]:
        request = HostTwoRoundInput.model_validate(data)
        if request.first_report_id == request.second_report_id:
            reject("Two-round acceptance needs two different actual reports.")
        first = self.get(request.first_report_id, request.candidate_id)
        second = self.get(request.second_report_id, request.candidate_id)
        if first["domain"] != second["domain"] or datetime.fromisoformat(
            str(second["started_at"])
        ) < datetime.fromisoformat(str(first["completed_at"])):
            reject("Acceptance reports must be sequential in the same domain.")
        return {
            "report_ids": [request.first_report_id, request.second_report_id],
            "core_checks_passed": bool(
                first["core_checks_passed"] and second["core_checks_passed"]
            ),
            "real_browser_verified": False,
            "host_verification": "requires_live_host_review",
            "evidence_modes": [first["evidence_mode"], second["evidence_mode"]],
        }
