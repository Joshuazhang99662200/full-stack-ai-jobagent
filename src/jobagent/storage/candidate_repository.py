"""SQLite adapter for Candidate Core repository operations."""

import sqlite3
from datetime import UTC, datetime

from jobagent.errors import StorageError
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    EvidenceItem,
    InterviewEvent,
    InterviewOutcome,
    ParsedResume,
)
from jobagent.storage.database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteCandidateRepository:
    """Persist Pydantic candidate contracts without leaking SQLite into the domain."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_profile(self, profile: CandidateProfile) -> None:
        timestamp = _now()
        try:
            with self.database.connect() as connection, connection:
                self._upsert_profile(connection, profile, timestamp)
        except sqlite3.Error as error:
            self._raise_storage_error("save candidate profile", error)

    def get_profile(self, candidate_id: str) -> CandidateProfile | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT profile_json FROM candidate_profiles WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load candidate profile", error)
        return None if row is None else CandidateProfile.model_validate_json(row["profile_json"])

    def upsert_evidence(self, candidate_id: str, evidence: EvidenceItem) -> None:
        timestamp = _now()
        try:
            with self.database.connect() as connection, connection:
                self._upsert_evidence(connection, candidate_id, evidence, timestamp)
        except sqlite3.Error as error:
            self._raise_storage_error("save candidate evidence", error)

    def get_evidence(self, candidate_id: str, evidence_id: str) -> EvidenceItem | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT evidence_json FROM evidence_items
                    WHERE candidate_id = ? AND evidence_id = ?
                    """,
                    (candidate_id, evidence_id),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load candidate evidence", error)
        return None if row is None else EvidenceItem.model_validate_json(row["evidence_json"])

    def list_evidence(self, candidate_id: str) -> list[EvidenceItem]:
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT evidence_json FROM evidence_items
                    WHERE candidate_id = ? ORDER BY evidence_id
                    """,
                    (candidate_id,),
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_storage_error("list candidate evidence", error)
        return [EvidenceItem.model_validate_json(row["evidence_json"]) for row in rows]

    def save_resume(self, resume: ParsedResume) -> None:
        try:
            with self.database.connect() as connection, connection:
                self._insert_resume(connection, resume, _now())
        except sqlite3.Error as error:
            self._raise_storage_error("save resume ingestion", error)

    def get_resume(self, resume_id: str) -> ParsedResume | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT resume_json FROM resume_ingestions WHERE resume_id = ?",
                    (resume_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("load resume ingestion", error)
        return None if row is None else ParsedResume.model_validate_json(row["resume_json"])

    def append_interview_event(self, event: InterviewEvent) -> None:
        try:
            with self.database.connect() as connection, connection:
                self._insert_interview_event(connection, event)
        except sqlite3.Error as error:
            self._raise_storage_error("append interview event", error)

    def list_interview_events(self, candidate_id: str) -> list[InterviewEvent]:
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM interview_events
                    WHERE candidate_id = ? ORDER BY created_at, event_id
                    """,
                    (candidate_id,),
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_storage_error("list interview events", error)
        return [InterviewEvent.model_validate_json(row["payload_json"]) for row in rows]

    def save_onboarding(self, resume: ParsedResume, draft: CandidateDraft) -> None:
        timestamp = _now()
        try:
            with self.database.connect() as connection, connection:
                self._upsert_profile(connection, draft.profile, timestamp)
                self._insert_resume(connection, resume, timestamp)
                for evidence in draft.evidence:
                    self._upsert_evidence(connection, draft.candidate_id, evidence, timestamp)
        except sqlite3.Error as error:
            self._raise_storage_error("save candidate onboarding", error)

    def save_draft(self, draft: CandidateDraft) -> None:
        timestamp = _now()
        try:
            with self.database.connect() as connection, connection:
                self._upsert_profile(connection, draft.profile, timestamp)
                for evidence in draft.evidence:
                    self._upsert_evidence(connection, draft.candidate_id, evidence, timestamp)
        except sqlite3.Error as error:
            self._raise_storage_error("save candidate draft", error)

    def save_interview_outcome(self, outcome: InterviewOutcome) -> None:
        try:
            with self.database.connect() as connection, connection:
                self._insert_interview_event(connection, outcome.event)
                if outcome.draft_evidence is not None:
                    self._upsert_evidence(
                        connection,
                        outcome.event.candidate_id,
                        outcome.draft_evidence,
                        _now(),
                    )
        except sqlite3.Error as error:
            self._raise_storage_error("save interview outcome", error)

    @staticmethod
    def _upsert_profile(
        connection: sqlite3.Connection,
        profile: CandidateProfile,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO candidate_profiles (candidate_id, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                profile_json = excluded.profile_json,
                updated_at = excluded.updated_at
            """,
            (profile.id, profile.model_dump_json(), timestamp, timestamp),
        )

    @staticmethod
    def _upsert_evidence(
        connection: sqlite3.Connection,
        candidate_id: str,
        evidence: EvidenceItem,
        timestamp: str,
    ) -> None:
        owner = connection.execute(
            "SELECT candidate_id FROM evidence_items WHERE evidence_id = ?",
            (evidence.id,),
        ).fetchone()
        if owner is not None and owner["candidate_id"] != candidate_id:
            raise StorageError(
                "Evidence ID belongs to another candidate.",
                details={"evidence_id": evidence.id, "candidate_id": candidate_id},
            )
        connection.execute(
            """
            INSERT INTO evidence_items (
                evidence_id, candidate_id, evidence_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                candidate_id = excluded.candidate_id,
                evidence_json = excluded.evidence_json,
                updated_at = excluded.updated_at
            """,
            (evidence.id, candidate_id, evidence.model_dump_json(), timestamp, timestamp),
        )

    @staticmethod
    def _insert_resume(
        connection: sqlite3.Connection,
        resume: ParsedResume,
        timestamp: str,
    ) -> None:
        owner = connection.execute(
            "SELECT candidate_id FROM resume_ingestions WHERE resume_id = ?",
            (resume.id,),
        ).fetchone()
        if owner is not None and owner["candidate_id"] != resume.candidate_id:
            raise StorageError(
                "Resume ID belongs to another candidate.",
                details={"resume_id": resume.id, "candidate_id": resume.candidate_id},
            )
        connection.execute(
            """
            INSERT INTO resume_ingestions (resume_id, candidate_id, resume_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(resume_id) DO UPDATE SET
                resume_json = excluded.resume_json
            """,
            (resume.id, resume.candidate_id, resume.model_dump_json(), timestamp),
        )

    @staticmethod
    def _insert_interview_event(
        connection: sqlite3.Connection,
        event: InterviewEvent,
    ) -> None:
        connection.execute(
            """
            INSERT INTO interview_events (
                event_id, candidate_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.candidate_id,
                event.event_type.value,
                event.model_dump_json(),
                event.created_at.isoformat(),
            ),
        )

    def _raise_storage_error(self, operation: str, error: sqlite3.Error) -> None:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
