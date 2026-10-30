"""SQLite adapter for Job Intelligence artifacts."""

import hashlib
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from jobagent.errors import ContractValidationError, StorageError
from jobagent.schemas.job_intelligence import (
    JobSearchHit,
    SearchRun,
    SourceJobRecord,
    StoredJobObservation,
)
from jobagent.schemas.jobs import (
    HardFilterResult,
    JobRequirementProfile,
    MatchResult,
    NormalizedJob,
)
from jobagent.storage.database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


class SqliteJobRepository:
    """Persist normalized jobs and candidate-scoped intelligence results."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_job(
        self, job: NormalizedJob, *, connection: sqlite3.Connection | None = None
    ) -> None:
        if connection is not None:
            self._save_job_in(connection, job)
            return
        try:
            with self.database.connect() as own_connection, own_connection:
                self._save_job_in(own_connection, job)
        except sqlite3.Error as error:
            self._raise_storage_error("save normalized job", error)

    @staticmethod
    def _save_job_in(
        connection: sqlite3.Connection, job: NormalizedJob, *, archive: bool = True,
    ) -> None:
        timestamp = _now()
        identities = [item.model_dump_json() for item in job.provenance]
        if len(set(identities)) != len(identities):
            raise sqlite3.IntegrityError("Duplicate input provenance.")
        connection.execute(
            """
            INSERT INTO normalized_jobs (job_id, job_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                job_json = excluded.job_json,
                updated_at = excluded.updated_at
            """,
            (job.id, job.model_dump_json(), timestamp, timestamp),
        )
        if archive:
            body = job.model_dump_json()
            connection.execute(
                "INSERT OR IGNORE INTO job_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_digest(body), job.id, None, None, body, "normalized_only",
                 job.collected_at.isoformat()),
            )
        for item in job.provenance:
            connection.execute(
                """INSERT OR IGNORE INTO job_provenance
                (job_id, source, source_id, url, collected_at)
                VALUES (?, ?, ?, ?, ?)""",
                (job.id, item.source, item.source_id,
                 str(item.url) if item.url is not None else "", item.collected_at.isoformat()),
            )

    def save_observation(
        self, record: SourceJobRecord, job: NormalizedJob,
        *, connection: sqlite3.Connection | None = None,
    ) -> None:
        if connection is None:
            try:
                with self.database.connect() as own, own:
                    own.execute("BEGIN IMMEDIATE")
                    self.save_observation(record, job, connection=own)
                return
            except sqlite3.Error as error:
                self._raise_storage_error("save observation", error)
        assert connection is not None
        from jobagent.jobs.normalization import JobNormalizer

        expected = JobNormalizer().normalize(record)
        if job.id != expected.id or job.observation_id != expected.observation_id:
            raise ContractValidationError("Observation and normalized job have different identity.")
        if record.read_attempt_id is not None:
            attempt = connection.execute(
                "SELECT request_json, result_json FROM sourcing_read_attempts WHERE attempt_id = ?",
                (record.read_attempt_id,),
            ).fetchone()
            from jobagent.schemas.sourcing import ReadOutcome, ReadReservation

            if attempt is None or attempt["result_json"] is None:
                raise ContractValidationError("Observation has no completed read attempt.")
            request = ReadReservation.model_validate_json(attempt["request_json"])
            outcome = ReadOutcome.model_validate_json(attempt["result_json"])
            if (request.source != record.source or request.target_url != record.url
                    or outcome.status != "read"):
                raise ContractValidationError("Read attempt does not match captured observation.")
            bound = connection.execute(
                "SELECT observation_id FROM job_observations "
                "WHERE json_extract(record_json, '$.read_attempt_id') = ?",
                (record.read_attempt_id,),
            ).fetchone()
            if bound is not None and bound[0] != job.observation_id:
                raise ContractValidationError("Read attempt is already bound to another capture.")
        self._save_job_in(connection, job, archive=False)
        connection.execute(
            "INSERT OR IGNORE INTO job_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job.observation_id, job.id, job.jd_digest, record.model_dump_json(),
             job.model_dump_json(), "captured", record.collected_at.isoformat()),
        )

    def observations(self, job_id: str) -> list[StoredJobObservation]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_observations WHERE job_id = ? ORDER BY collected_at, rowid",
                (job_id,),
            ).fetchall()
        return [StoredJobObservation(
            observation_id=row["observation_id"], job_id=row["job_id"],
            content_digest=row["content_digest"],
            record=SourceJobRecord.model_validate_json(row["record_json"])
            if row["record_json"] is not None else None,
            normalized=NormalizedJob.model_validate_json(row["normalized_json"]), kind=row["kind"],
        ) for row in rows]

    def record_search_hit(
        self, hit: JobSearchHit, *, connection: sqlite3.Connection | None = None
    ) -> None:
        if connection is not None:
            self._record_search_hit_in(connection, hit)
            return
        try:
            with self.database.connect() as connection, connection:
                self._record_search_hit_in(connection, hit)
        except sqlite3.Error as error:
            self._raise_storage_error("record job search hit", error)

    @staticmethod
    def _record_search_hit_in(connection: sqlite3.Connection, hit: JobSearchHit) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO job_search_hits "
            "(job_id, source, search_term, collected_at) VALUES (?, ?, ?, ?)",
            (hit.job_id, hit.source, hit.search_term, hit.collected_at.isoformat()),
        )

    def record_search(self, run: SearchRun) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT INTO job_searches (source, search_term, searched_at, results, new) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        run.source,
                        run.search_term,
                        run.searched_at.isoformat(),
                        run.results,
                        run.new,
                    ),
                )
        except sqlite3.Error as error:
            self._raise_storage_error("record job search", error)

    def searches(self) -> list[SearchRun]:
        """Every logged search, oldest first."""
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT source, search_term, searched_at, results, new FROM job_searches "
                    "ORDER BY searched_at, source, search_term"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_storage_error("read job searches", error)
        return [
            SearchRun(
                source=row["source"],
                search_term=row["search_term"],
                searched_at=datetime.fromisoformat(row["searched_at"]),
                results=row["results"],
                new=row["new"],
            )
            for row in rows
        ]

    def search_hits(self) -> list[JobSearchHit]:
        """Every recorded search hit, oldest first."""
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT job_id, source, search_term, collected_at FROM job_search_hits "
                    "ORDER BY collected_at, job_id, search_term"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_storage_error("read job search hits", error)
        return [
            JobSearchHit(
                job_id=row["job_id"],
                source=row["source"],
                search_term=row["search_term"],
                collected_at=datetime.fromisoformat(row["collected_at"]),
            )
            for row in rows
        ]

    def get_job(self, job_id: str) -> NormalizedJob | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT job_json FROM normalized_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load normalized job", error)
        return None if row is None else NormalizedJob.model_validate_json(row["job_json"])

    def list_jobs(self) -> list[NormalizedJob]:
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT job_json FROM normalized_jobs ORDER BY job_id"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_storage_error("list normalized jobs", error)
        return [NormalizedJob.model_validate_json(row["job_json"]) for row in rows]

    def save_requirements(self, profile: JobRequirementProfile) -> str:
        content = profile.model_dump_json()
        content_digest = _digest(content)
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    """
                    INSERT INTO job_requirements (
                        job_id, requirements_json, content_digest, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        requirements_json = excluded.requirements_json,
                        content_digest = excluded.content_digest,
                        updated_at = excluded.updated_at
                    """,
                    (profile.job_id, content, content_digest, _now()),
                )
        except sqlite3.Error as error:
            self._raise_storage_error("save job requirements", error)
        return content_digest

    def get_requirements(self, job_id: str) -> JobRequirementProfile | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT requirements_json FROM job_requirements WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load job requirements", error)
        return (
            None
            if row is None
            else JobRequirementProfile.model_validate_json(row["requirements_json"])
        )

    def save_filter_result(
        self,
        candidate_id: str,
        job_id: str,
        policy_digest: str,
        result: HardFilterResult,
    ) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    """
                    INSERT INTO hard_filter_results (
                        candidate_id, job_id, policy_digest, result_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_id, job_id, policy_digest) DO UPDATE SET
                        result_json = excluded.result_json,
                        updated_at = excluded.updated_at
                    """,
                    (candidate_id, job_id, policy_digest, result.model_dump_json(), _now()),
                )
        except sqlite3.Error as error:
            self._raise_storage_error("save hard filter result", error)

    def get_filter_result(
        self,
        candidate_id: str,
        job_id: str,
        policy_digest: str,
    ) -> HardFilterResult | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT result_json FROM hard_filter_results
                    WHERE candidate_id = ? AND job_id = ? AND policy_digest = ?
                    """,
                    (candidate_id, job_id, policy_digest),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load hard filter result", error)
        return None if row is None else HardFilterResult.model_validate_json(row["result_json"])

    def save_match(
        self,
        candidate_id: str,
        job_id: str,
        *,
        evidence_digest: str,
        requirements_digest: str,
        policy_digest: str,
        result: MatchResult,
    ) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    """
                    INSERT INTO job_matches (
                        candidate_id, job_id, evidence_digest, requirements_digest,
                        policy_digest, result_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        candidate_id, job_id, evidence_digest,
                        requirements_digest, policy_digest
                    ) DO UPDATE SET
                        result_json = excluded.result_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        candidate_id,
                        job_id,
                        evidence_digest,
                        requirements_digest,
                        policy_digest,
                        result.model_dump_json(),
                        _now(),
                    ),
                )
        except sqlite3.Error as error:
            self._raise_storage_error("save job match", error)

    def latest_match_tiers(self, candidate_id: str, job_ids: Sequence[str]) -> dict[str, str]:
        """The most recent match decision per job for this candidate."""
        tiers: dict[str, str] = {}
        try:
            with self.database.connect() as connection:
                for job_id in job_ids:
                    row = connection.execute(
                        "SELECT result_json FROM job_matches WHERE candidate_id = ? AND job_id = ? "
                        "ORDER BY updated_at DESC LIMIT 1",
                        (candidate_id, job_id),
                    ).fetchone()
                    if row is not None:
                        tiers[job_id] = MatchResult.model_validate_json(row[0]).decision.value
        except sqlite3.Error as error:
            self._raise_storage_error("read match tiers", error)
        return tiers

    def get_match(
        self,
        candidate_id: str,
        job_id: str,
        *,
        evidence_digest: str,
        requirements_digest: str,
        policy_digest: str,
    ) -> MatchResult | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT result_json FROM job_matches
                    WHERE candidate_id = ? AND job_id = ?
                      AND evidence_digest = ? AND requirements_digest = ?
                      AND policy_digest = ?
                    """,
                    (
                        candidate_id,
                        job_id,
                        evidence_digest,
                        requirements_digest,
                        policy_digest,
                    ),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load job match", error)
        return None if row is None else MatchResult.model_validate_json(row["result_json"])

    def _raise_storage_error(self, operation: str, error: sqlite3.Error) -> None:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
