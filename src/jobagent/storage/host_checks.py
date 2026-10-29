"""Persist page settling evidence and pause affected message tracking on login loss."""

import json
from datetime import datetime

from jobagent.jobs.host_checks import page_decision
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.sent_tracking import ACTIVE
from jobagent.schemas.host_checks import HostPageObservation
from jobagent.schemas.pipeline import PipelineObservation
from jobagent.schemas.sent_tracking import TrackingEventInput
from jobagent.storage.database import Database
from jobagent.storage.pipeline_repository import PipelineRepository
from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository


class HostPageService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.tracking = SqliteSentTrackingRepository(database)

    def record(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        observation = HostPageObservation.model_validate(data)
        digest = canonical_digest(observation.model_dump(mode="json"))
        if observation.observed_at > now:
            reject("Page evidence cannot come from the future.")
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT * FROM host_page_observations WHERE observation_id = ?",
                (observation.observation_id,),
            ).fetchone()
            if old:
                if old["input_digest"] != digest:
                    reject("Page observation ID has different content.")
                previous: dict[str, object] = json.loads(old["response_json"])
                if not previous.get("pending"):
                    return previous
            else:
                connection.execute(
                    "INSERT INTO host_page_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        observation.observation_id,
                        observation.candidate_id,
                        observation.source,
                        observation.surface,
                        observation.observed_at.isoformat(),
                        digest,
                        observation.model_dump_json(),
                        json.dumps({"pending": True}),
                    ),
                )
        result = page_decision(observation)
        latest = self.latest(observation.candidate_id)
        current = latest.get(observation.source + "/" + observation.surface)
        stale = current is not None and current["observation_id"] != observation.observation_id
        paused = []
        paused_pipeline = []
        with self.database.connect() as connection:
            authority = connection.execute(
                "SELECT activated_at FROM pipeline_authorities WHERE candidate_id = ?",
                (observation.candidate_id,),
            ).fetchone()
        if (
            not stale
            and observation.surface == "messages"
            and observation.state == "login_redirect"
        ):
            if authority is not None:
                if observation.observed_at >= datetime.fromisoformat(authority[0]):
                    paused_pipeline = self._pause_pipeline(observation, now=now)
            else:
                paused = self._pause_legacy(observation, now=now)
        result.update(
            paused_tracking_ids=paused,
            paused_pipeline_ids=paused_pipeline,
            state_authority="pipeline_jobs" if authority is not None else "legacy_tracking",
            stale=stale,
            observation_id=observation.observation_id,
            observed_at=observation.observed_at.isoformat(),
        )
        if stale:
            result.update(
                notification_required=False, needs_user_action=False, action="stale_observation"
            )
        with self.database.connect() as connection, connection:
            connection.execute(
                "UPDATE host_page_observations SET response_json = ? WHERE observation_id = ?",
                (json.dumps(result, ensure_ascii=False), observation.observation_id),
            )
        return result

    def _pause_pipeline(self, observation: HostPageObservation, *, now: datetime) -> list[str]:
        repository = PipelineRepository(self.database)
        paused = []
        for job, meta in repository.list_records(observation.candidate_id):
            if job.platform != observation.source or job.pipeline_state == "abandoned":
                continue
            event_id = (
                "HOST_PIPE_" + canonical_digest([observation.observation_id, job.pipeline_id])[7:]
            )
            with self.database.connect() as connection:
                existing = connection.execute(
                    "SELECT candidate_id,pipeline_id FROM pipeline_requests WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            if existing:
                if (
                    existing["candidate_id"] != observation.candidate_id
                    or existing["pipeline_id"] != job.pipeline_id
                ):
                    reject("Page pause event conflicts with another pipeline target.")
                paused.append(job.pipeline_id)
                continue
            if observation.observed_at < job.updated_at:
                continue
            repository.observe(
                PipelineObservation(
                    event_id=event_id,
                    pipeline_id=job.pipeline_id,
                    candidate_id=job.candidate_id,
                    expected_version=meta.version,
                    kind="pause",
                    observed_at=observation.observed_at,
                    evidence_kind="platform_state",
                    evidence_reference=observation.evidence_reference,
                ),
                now=now,
            )
            paused.append(job.pipeline_id)
        return paused

    def _pause_legacy(self, observation: HostPageObservation, *, now: datetime) -> list[str]:
        paused = []
        for record in self.tracking.list_records(observation.candidate_id):
            if record.platform != observation.source or record.tracking_state not in ACTIVE:
                continue
            event_id = (
                "HOST_" + canonical_digest([observation.observation_id, record.tracking_id])[7:]
            )
            if any(
                e.event_id == event_id
                for e in self.tracking.history(
                    record.tracking_id,
                    record.candidate_id,
                )
            ):
                paused.append(record.tracking_id)
                continue
            if observation.observed_at < record.last_event_at:
                continue
            self.tracking.apply(
                TrackingEventInput(
                    event_id=event_id,
                    tracking_id=record.tracking_id,
                    candidate_id=record.candidate_id,
                    expected_version=record.tracking_version,
                    kind="anomaly",
                    observed_at=observation.observed_at,
                    observation_id=observation.observation_id,
                    evidence_reference=observation.evidence_reference,
                    evidence_kind="platform_state",
                ),
                now=now,
            )
            paused.append(record.tracking_id)
        return paused

    def latest(
        self, candidate_id: str, *, at: datetime | None = None
    ) -> dict[str, dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT observation_json FROM host_page_observations WHERE candidate_id = ? "
                "ORDER BY rowid",
                (candidate_id,),
            ).fetchall()
        result = {}
        observations = sorted(
            (HostPageObservation.model_validate_json(row["observation_json"]) for row in rows),
            key=lambda value: value.observed_at,
        )
        for observation in observations:
            if at is not None and observation.observed_at > at:
                continue
            result[observation.source + "/" + observation.surface] = observation.model_dump(
                mode="json"
            )
        return result
