"""SQLite adapter for Job Intelligence artifacts."""

import hashlib
import sqlite3
from datetime import UTC, datetime

from jobagent.errors import StorageError
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

    def save_job(self, job: NormalizedJob) -> None:
        timestamp = _now()
        try:
            with self.database.connect() as connection, connection:
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
                connection.execute("DELETE FROM job_provenance WHERE job_id = ?", (job.id,))
                for item in job.provenance:
                    connection.execute(
                        """
                        INSERT INTO job_provenance (
                            job_id, source, source_id, url, collected_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            job.id,
                            item.source,
                            item.source_id,
                            str(item.url) if item.url is not None else "",
                            item.collected_at.isoformat(),
                        ),
                    )
        except sqlite3.Error as error:
            self._raise_storage_error("save normalized job", error)

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
