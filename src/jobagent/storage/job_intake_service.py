"""Compose cached artifacts into intake progress without browsing or sending."""

from datetime import datetime
from typing import TypeVar

from jobagent.jobs.jd_factorization import factorize
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.lexicon import lexicon_digest
from jobagent.outreach.service import contacted_job_ids
from jobagent.schemas.jd_snapshot import JDSnapshotInput
from jobagent.schemas.job_intake import (
    IntakeCommand,
    IntakeControl,
    IntakeHistory,
    IntakeInterest,
    IntakeRecord,
    IntakeRequest,
    IntakeResolve,
    IntakeSelection,
    IntakeSnapshot,
)
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.lexicon import JDFeatureSet, Lexicon
from jobagent.schemas.search_learning import SearchSignal
from jobagent.schemas.sourcing import SourcingAttempt, SourcingResult
from jobagent.storage.database import Database
from jobagent.storage.intake_drafting import IntakeDraftingService
from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository
from jobagent.storage.job_intake_repository import SqliteJobIntakeRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.sourcing_repository import SqliteSourcingRepository

CommandT = TypeVar("CommandT", bound=IntakeCommand)


class JobIntakeService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = SqliteJobIntakeRepository(database)
        self.knowledge = SqliteJDSnapshotRepository(database)
        self.jobs = SqliteJobRepository(database)
        self.outreach = SqliteOutreachRepository(database)

    def prepare(
        self, command: IntakeCommand, kind: str, extra: object = None
    ) -> tuple[IntakeRecord, str, bool]:
        command_data = command.model_dump(mode="json")
        if isinstance(command, IntakeSnapshot) and command.observation_id is None:
            command_data.pop("observation_id", None)  # Preserve PR5 retry digests.
        digest = canonical_digest([kind, command_data, extra])
        current = self.repository.get(command.intake_id, command.candidate_id)
        with self.database.connect() as connection:
            old = connection.execute(
                "SELECT event_json FROM intake_events WHERE event_id = ?", (command.event_id,)
            ).fetchone()
        if old:
            event = IntakeHistory.model_validate_json(old["event_json"])
            if event.state.intake_id != current.intake_id or event.command_digest != digest:
                reject("Operation ID has different input.")
            return event.state, digest, True
        if current.version != command.expected_version:
            reject("Intake changed; reload its current version.")
        if current.closed or current.merged_into:
            reject("Closed or merged intake cannot be changed.")
        if current.paused and kind not in {"control", "synchronize"}:
            reject("Intake is paused pending owner action.")
        return current, digest, False

    def commit(
        self,
        command: IntakeCommand,
        kind: str,
        changes: dict[str, object],
        now: datetime,
        digest: str,
        signal: SearchSignal | None = None,
    ) -> IntakeRecord:
        return self.repository.update(
            command.intake_id,
            command.candidate_id,
            event_id=command.event_id,
            expected_version=command.expected_version,
            kind=kind,
            changes=changes,
            now=now,
            signal=signal,
            command_digest=digest,
        )

    def job(self, record: IntakeRecord) -> NormalizedJob:
        job = self.jobs.get_job(record.job_id or "")
        if job is None:
            reject("A cached resolved job is required.")
        assert job is not None
        return job

    def bound(self, record: IntakeRecord) -> NormalizedJob:
        job = self.job(record)
        if record.snapshot_id is None:
            reject("Complete JD is required before drafting or learning.")
        snapshot = self.knowledge.get(record.snapshot_id or "")
        latest = self.knowledge.list_snapshots(job.id)[-1]
        if (
            latest.snapshot_id != snapshot.snapshot_id
            or snapshot.completeness != "full"
            or job.jd_raw.strip() != snapshot.jd_text.strip()
        ):
            reject("JD changed; synchronize intake and fetch the current full text.")
        return job

    def merge(
        self,
        source: IntakeRecord,
        target: IntakeRecord,
        *,
        command: IntakeCommand,
        digest: str,
        now: datetime,
    ) -> IntakeRecord:
        with self.repository.write() as connection:
            current = self.repository.current(connection, source.intake_id, source.candidate_id)
            existing = self.repository.current(connection, target.intake_id, target.candidate_id)
            if (
                current.version != source.version
                or existing.version != target.version
                or current.closed
                or existing.closed
            ):
                reject("Intake changed while merging matching job identities.")
            request_ids = {r.request_id for r in existing.requests}
            additions = [r for r in current.requests if r.request_id not in request_ids]
            # An older message discovered late must not replace a newer preference.
            requests = sorted(
                [*existing.requests, *additions], key=lambda r: (r.occurred_at, r.request_id)
            )
            previous_choice = next(
                (r for r in reversed(existing.requests) if r.job_preference is not None), None
            )
            next_choice = next(
                (r for r in reversed(requests) if r.job_preference is not None), None
            )
            interest_changed = previous_choice != next_choice
            merged = existing.model_copy(
                update={
                    "requests": requests,
                    "version": existing.version + 1,
                    "updated_at": now,
                    "signal_id": None if interest_changed else existing.signal_id,
                    "plan_id": None if interest_changed else existing.plan_id,
                }
            )
            alias = current.model_copy(
                update={
                    "merged_into": existing.intake_id,
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            self.repository.append(
                connection,
                alias,
                command.event_id,
                "identity_merged",
                digest,
                command_digest=digest,
            )
            self.repository.append(
                connection, merged, command.event_id + ":target", "source_merged", digest
            )
            connection.execute(
                "UPDATE intake_requests SET intake_id = ? WHERE intake_id = ?",
                (merged.intake_id, alias.intake_id),
            )
        return self.refresh_interest(merged, now=now)

    def refresh_interest(self, row: IntakeRecord, *, now: datetime) -> IntakeRecord:
        if row.feature_set_id is None or row.signal_id is not None:
            return row
        signal = self.signal(row, self.features(row.feature_set_id))
        if signal is None:
            return row
        return self.repository.update(
            row.intake_id,
            row.candidate_id,
            event_id="ATTACH_" + signal.event_id,
            expected_version=row.version,
            kind="interest_attached",
            changes={"signal_id": signal.event_id, "plan_id": None},
            signal=signal,
            now=now,
        )

    def enqueue(self, request: IntakeRequest, *, now: datetime) -> IntakeRecord:
        row = self.repository.enqueue(request, now=now)
        return self.synchronize(row.intake_id, row.candidate_id, now=now)

    def save_selection(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        evidence = IntakeSelection.model_validate(data)
        if evidence.observed_at > now:
            reject("Selection evidence cannot come from the future.")
        for target in evidence.targets.values():
            job = self.jobs.get_job(target) if isinstance(target, str) else target
            if job is None or job.source != evidence.platform:
                reject("Every list target must resolve to a cached job on the same platform.")
        digest = canonical_digest(evidence.model_dump(mode="json"))
        with self.repository.write() as connection:
            old = connection.execute(
                "SELECT input_digest FROM intake_selections WHERE candidate_id = ? "
                "AND platform = ? AND list_version = ?",
                (evidence.candidate_id, evidence.platform, evidence.list_version),
            ).fetchone()
            if old and old["input_digest"] != digest:
                reject("A list version cannot change its message or numbered targets.")
            connection.execute(
                "INSERT OR IGNORE INTO intake_selections VALUES (?, ?, ?, ?, ?)",
                (
                    evidence.candidate_id,
                    evidence.platform,
                    evidence.list_version,
                    digest,
                    evidence.model_dump_json(),
                ),
            )
        return {
            "list_version": evidence.list_version,
            "input_digest": digest,
            "target_count": len(evidence.targets),
        }

    def verify_selection(self, row: IntakeRecord, job: NormalizedJob | JobListing) -> None:
        if row.job_url is not None or row.source_job_id is not None:
            return
        request = row.requests[0]
        with self.database.connect() as connection:
            stored = connection.execute(
                "SELECT selection_json FROM intake_selections WHERE candidate_id = ? "
                "AND platform = ? AND list_version = ?",
                (row.candidate_id, row.platform, request.list_version or request.message_reference),
            ).fetchone()
        if stored is None:
            reject("Store the immutable list/card target mapping before resolving this reference.")
        evidence = IntakeSelection.model_validate_json(stored["selection_json"])
        expected = evidence.targets.get(request.target_reference)
        target = self.jobs.get_job(expected) if isinstance(expected, str) else expected
        if (
            target is None
            or evidence.message_reference != request.message_reference
            or target.source_job_id != job.source_job_id
            or target.url != job.url
        ):
            reject("The selected number or card points to another actual job.")

    def resolve(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeResolve.model_validate(data)
        row, digest, replay = self.prepare(cmd, "resolve")
        if replay:
            return (
                self.repository.get(row.merged_into, row.candidate_id) if row.merged_into else row
            )
        observed = self.jobs.get_job(cmd.job_id) if cmd.job_id else cmd.listing
        if observed is None or observed.source != row.platform:
            reject("Identity needs an actual listing or cached job on the requested platform.")
        if isinstance(observed, JobListing) and (
            observed.collected_at.tzinfo is None or observed.collected_at > now
        ):
            reject("Listing observation must be timezone-aware and not from the future.")
        self.verify_selection(row, observed)
        if (row.job_url is not None and row.job_url != observed.url) or (
            row.source_job_id is not None and row.source_job_id != observed.source_job_id
        ):
            reject("Resolved job differs from the original target.")
        cached = (
            observed
            if isinstance(observed, NormalizedJob)
            else next(
                (
                    j
                    for j in self.jobs.list_jobs()
                    if j.source == observed.source
                    and j.source_job_id == observed.source_job_id
                    and j.url == observed.url
                ),
                None,
            )
        )
        if row.job_id is not None and (cached is None or row.job_id != cached.id):
            reject("The resolved job identity cannot change.")
        duplicate = next(
            (
                r
                for r in self.repository.list_records(row.candidate_id, row.domain)
                if r.intake_id != row.intake_id
                and not r.merged_into
                and not r.closed
                and r.platform == row.platform
                and (
                    (cached is not None and r.job_id == cached.id)
                    or (r.source_job_id == observed.source_job_id and r.job_url == observed.url)
                )
            ),
            None,
        )
        if duplicate:
            return self.merge(row, duplicate, command=cmd, digest=digest, now=now)
        return self.commit(
            cmd,
            "resolve",
            {
                "job_id": cached.id if cached else None,
                "job_url": observed.url,
                "source_job_id": observed.source_job_id,
                "listing": observed if isinstance(observed, JobListing) else row.listing,
                "contacted": cached.id in contacted_job_ids(self.outreach.list_audits())
                if cached
                else False,
            },
            now,
            digest,
        )

    def attach_snapshot(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeSnapshot.model_validate(data)
        row, digest, replay = self.prepare(cmd, "snapshot")
        if replay:
            return row
        snapshot = self.knowledge.get(cmd.snapshot_id)
        observation = next(
            (
                d
                for d in self.knowledge.discoveries(snapshot.job_id)
                if d.observation_id == (cmd.observation_id or snapshot.observation_id)
            ),
            None,
        )
        if observation is None or observation.snapshot_id != snapshot.snapshot_id:
            reject("Snapshot observation must reference this exact content version.")
        fetched_at = observation.fetched_at
        job = self.jobs.get_job(row.job_id or snapshot.job_id)
        if (
            job is None
            or job.source != row.platform
            or job.url != row.job_url
            or job.source_job_id != row.source_job_id
        ):
            reject("The full JD does not match the resolved listing identity.")
        if (
            snapshot.job_id != job.id
            or snapshot.job_url != job.url
            or snapshot.platform != job.source
            or snapshot.completeness != "full"
            or snapshot.snapshot_id != self.knowledge.list_snapshots(job.id)[-1].snapshot_id
            or fetched_at > now
        ):
            reject("Snapshot must be the matching current complete JD.")
        if cmd.attempt_id is None:
            if fetched_at >= row.created_at:
                reject("A new platform detail fetch needs its recorded sourcing attempt.")
        else:
            with self.database.connect() as connection:
                attempt_row = connection.execute(
                    "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
                    (cmd.attempt_id,),
                ).fetchone()
                result_row = connection.execute(
                    "SELECT result_json FROM sourcing_results WHERE attempt_id = ?",
                    (cmd.attempt_id,),
                ).fetchone()
            if attempt_row is None or result_row is None:
                reject("The detail read needs an existing completed sourcing attempt.")
            assert attempt_row is not None and result_row is not None
            attempt = SourcingAttempt.model_validate_json(attempt_row["attempt_json"])
            result = SourcingResult.model_validate_json(result_row["result_json"])
            run = SqliteSourcingRepository(self.database).get_run(attempt.run_id)
            if not (
                attempt.kind == "detail"
                and attempt.source == row.platform
                and attempt.source_job_id == job.source_job_id
                and attempt.url == job.url
                and run.candidate_id == row.candidate_id
                and result.outcome == "complete"
                and attempt.occurred_at <= fetched_at <= result.completed_at <= now
            ):
                reject("Detail evidence does not match this read, candidate or target.")
        if job.jd_raw.strip() != snapshot.jd_text.strip():
            reject("Update the cached normalized job from the same full JD before attaching.")
        discovery = JDSnapshotInput.model_validate(
            {
                **snapshot.model_dump(
                    exclude={
                        "snapshot_id",
                        "snapshot_version",
                        "jd_text_hash",
                        "content_digest",
                    }
                ),
                "observation_id": "INTAKE_"
                + canonical_digest(
                    [row.intake_id, cmd.snapshot_id, cmd.observation_id, cmd.attempt_id]
                )[7:],
                "fetched_at": fetched_at,
                "discovery_kind": "manual",
                "query_hit": None,
            }
        )
        self.knowledge.capture(discovery)
        return self.commit(
            cmd,
            "snapshot",
            {
                "job_id": job.id,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_version": snapshot.snapshot_version,
                "jd_text_hash": snapshot.jd_text_hash,
                "blocked_reason": None,
                "feature_set_id": None,
                "feature_policy_digest": None,
                "signal_id": None,
                "draft": None,
                "draft_digest": None,
                "review": None,
                "batch_id": None,
                "plan_id": None,
            },
            now,
            digest,
        )

    def features(self, feature_id: str) -> JDFeatureSet:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT feature_json FROM jd_feature_sets WHERE feature_set_id = ?", (feature_id,)
            ).fetchone()
        if row is None:
            reject("Persisted feature set not found.")
        assert row is not None
        return JDFeatureSet.model_validate_json(row["feature_json"])

    def signal(self, row: IntakeRecord, features: JDFeatureSet) -> SearchSignal | None:
        choice = next((r for r in reversed(row.requests) if r.job_preference is not None), None)
        if choice is None:
            return None
        job = self.job(row)
        snapshot = self.knowledge.get(features.snapshot_id)
        quotes: dict[str, str] = {}
        for feature in features.features:
            if feature.polarity == "positive" and feature.term in feature.evidence:
                quotes.setdefault(feature.term, feature.evidence)
        if len(quotes) > 12:
            reject("Too many feedback features; narrow the domain before recording interest.")
        return SearchSignal(
            event_id="SIG_"
            + canonical_digest(
                [
                    row.intake_id,
                    choice.request_id,
                    features.snapshot_id,
                    [f.model_dump(mode="json") for f in features.features],
                ]
            )[7:],
            candidate_id=row.candidate_id,
            kind="user_added" if choice.job_preference == "like" else "feedback",
            job_preference=None if choice.job_preference == "like" else choice.job_preference,
            occurred_at=choice.occurred_at,
            owner_text=choice.owner_text,
            features=quotes,
            job=SourceJobRecord(
                source=job.source,
                source_job_id=job.source_job_id,
                title=job.title,
                company=job.company,
                location=job.location,
                jd_raw=snapshot.jd_text,
                url=job.url,
                collected_at=snapshot.fetched_at,
            ),
        )

    def factorize(
        self, data: dict[str, object], policy: Lexicon, *, proposal: object | None, now: datetime
    ) -> IntakeRecord:
        cmd = IntakeCommand.model_validate(data)
        row, digest, replay = self.prepare(
            cmd, "factorize", [policy.model_dump(mode="json"), proposal]
        )
        if replay:
            return row
        self.bound(row)
        if policy.domain != row.domain:
            reject("Lexicon belongs to another domain.")
        features = factorize(self.knowledge.get(row.snapshot_id or ""), policy, proposal)
        feature_id = self.knowledge.save_features(features, lexicon_digest(policy))
        signal = self.signal(row, features)
        return self.commit(
            cmd,
            "factorize",
            {
                "feature_set_id": feature_id,
                "feature_policy_digest": lexicon_digest(policy),
                "signal_id": signal.event_id if signal else None,
                "plan_id": None,
            },
            now,
            digest,
            signal,
        )

    def set_interest(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeInterest.model_validate(data)
        row, digest, replay = self.prepare(cmd, "interest")
        if replay:
            return row
        choice = row.requests[-1].model_copy(
            update={
                "request_id": "INTEREST_" + canonical_digest(cmd.event_id)[7:],
                "owner_text": cmd.owner_text,
                "message_reference": cmd.message_reference,
                "job_preference": cmd.job_preference,
                "occurred_at": now,
            }
        )
        updated = row.model_copy(update={"requests": [*row.requests, choice]})
        signal = (
            self.signal(updated, self.features(row.feature_set_id)) if row.feature_set_id else None
        )
        return self.commit(
            cmd,
            "interest",
            {
                "requests": updated.requests,
                "signal_id": signal.event_id if signal else None,
                "plan_id": None,
            },
            now,
            digest,
            signal,
        )

    def submit_draft(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        return IntakeDraftingService(self).submit_draft(data, now=now)

    def review_draft(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        return IntakeDraftingService(self).review_draft(data, now=now)

    def attach_batch(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        return IntakeDraftingService(self).attach_batch(data, now=now)

    def synchronize(self, intake_id: str, candidate_id: str, *, now: datetime) -> IntakeRecord:
        row = self.repository.get(intake_id, candidate_id)
        if row.job_id is None or row.closed or row.merged_into:
            return row
        changes: dict[str, object] = {}
        contacted = row.job_id in contacted_job_ids(self.outreach.list_audits())
        if contacted != row.contacted:
            changes["contacted"] = contacted
        snapshots = self.knowledge.list_snapshots(row.job_id)
        if row.snapshot_id and (
            not snapshots
            or snapshots[-1].snapshot_id != row.snapshot_id
            or self.job(row).jd_raw.strip() != snapshots[-1].jd_text.strip()
        ):
            changes.update(
                snapshot_id=None,
                snapshot_version=None,
                jd_text_hash=None,
                feature_set_id=None,
                feature_policy_digest=None,
                signal_id=None,
                draft=None,
                draft_digest=None,
                review=None,
                batch_id=None,
                plan_id=None,
                blocked_reason="jd_changed",
            )
        if not changes:
            return row if row.paused else self.refresh_interest(row, now=now)
        return self.repository.update(
            row.intake_id,
            row.candidate_id,
            event_id="SYNC_" + canonical_digest([row.intake_id, row.version, changes])[7:],
            expected_version=row.version,
            kind="synchronize",
            changes=changes,
            now=now,
        )

    def control(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeControl.model_validate(data)
        row, digest, replay = self.prepare(cmd, "control")
        if replay:
            return row
        if cmd.action in {"resume", "close"} and not (cmd.owner_text and cmd.owner_text.strip()):
            reject("Resume and closure require actual owner's words.")
        return self.commit(
            cmd,
            "control",
            {
                "paused": cmd.action == "pause",
                "closed": cmd.action == "close",
                "blocked_reason": cmd.reason if cmd.action != "resume" else None,
            },
            now,
            digest,
        )
