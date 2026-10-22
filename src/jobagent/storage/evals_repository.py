"""SQLite adapter for evaluation signals: harness versions and online profiles."""

import sqlite3
from typing import Never

from jobagent.errors import StorageError
from jobagent.schemas.evals import HarnessVersion
from jobagent.schemas.profile import (
    ProfileApplication,
    ProfileApproval,
    ProfileAsk,
    ProfileProposal,
    ProfileSnapshot,
    ProfileVersion,
)
from jobagent.storage.database import Database


class SqliteEvalsRepository:
    """Every row here is only ever added."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_harness_version(self, version: HarnessVersion) -> None:
        """Keep a version once; the same files seen again keep their first record."""
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT OR IGNORE INTO harness_versions "
                    "(version_id, digest, version_json, recorded_at) VALUES (?, ?, ?, ?)",
                    (
                        version.version_id,
                        version.digest,
                        version.model_dump_json(),
                        version.recorded_at.isoformat(),
                    ),
                )
        except sqlite3.Error as error:
            self._raise("save harness version", error)

    def get_harness_version(self, version_id: str) -> HarnessVersion | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT version_json AS body FROM harness_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise("read harness version", error)
        return HarnessVersion.model_validate_json(row["body"]) if row else None

    def save_profile_snapshot(self, snapshot: ProfileSnapshot) -> None:
        self._write(
            "save profile snapshot",
            "INSERT INTO profile_snapshots "
            "(snapshot_id, platform, captured_at, digest, snapshot_json) VALUES (?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.platform,
                snapshot.captured_at.isoformat(),
                snapshot.digest,
                snapshot.model_dump_json(),
            ),
        )

    def get_profile_snapshot(self, snapshot_id: str) -> ProfileSnapshot | None:
        rows = self._read(
            "read profile snapshot",
            "SELECT snapshot_json AS body FROM profile_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        return ProfileSnapshot.model_validate_json(rows[0]["body"]) if rows else None

    def save_profile_version(self, version: ProfileVersion) -> None:
        self._write(
            "save profile version",
            "INSERT INTO profile_versions "
            "(version_id, platform, digest, effective_at, version_json) VALUES (?, ?, ?, ?, ?)",
            (
                version.version_id,
                version.platform,
                version.digest,
                version.effective_at.isoformat(),
                version.model_dump_json(),
            ),
        )

    def profile_versions(self, platform: str) -> list[ProfileVersion]:
        """A board's profile versions, oldest first."""
        rows = self._read(
            "list profile versions",
            "SELECT version_json AS body FROM profile_versions WHERE platform = ? "
            "ORDER BY effective_at, version_id",
            (platform,),
        )
        return [ProfileVersion.model_validate_json(row["body"]) for row in rows]

    def latest_profile(self, platform: str) -> tuple[ProfileVersion, ProfileSnapshot] | None:
        """A board's current version and the snapshot that opened it."""
        versions = self.profile_versions(platform)
        if not versions:
            return None
        snapshot = self.get_profile_snapshot(versions[-1].snapshot_id)
        return (versions[-1], snapshot) if snapshot is not None else None

    def save_profile_proposal(self, proposal: ProfileProposal) -> None:
        self._write(
            "save profile proposal",
            "INSERT INTO profile_proposals (proposal_id, proposal_json, created_at) "
            "VALUES (?, ?, ?)",
            (proposal.proposal_id, proposal.model_dump_json(), proposal.created_at.isoformat()),
        )

    def get_profile_proposal(self, proposal_id: str) -> ProfileProposal | None:
        rows = self._read(
            "read profile proposal",
            "SELECT proposal_json AS body FROM profile_proposals WHERE proposal_id = ?",
            (proposal_id,),
        )
        return ProfileProposal.model_validate_json(rows[0]["body"]) if rows else None

    def save_profile_ask(self, ask: ProfileAsk) -> None:
        self._write(
            "save profile question",
            "INSERT OR REPLACE INTO profile_asks (ask_id, proposal_id, ask_json) VALUES (?, ?, ?)",
            (ask.ask_id, ask.proposal_id, ask.model_dump_json()),
        )

    def get_profile_ask(self, ask_id: str) -> ProfileAsk | None:
        rows = self._read(
            "read profile question",
            "SELECT ask_json AS body FROM profile_asks WHERE ask_id = ?",
            (ask_id,),
        )
        return ProfileAsk.model_validate_json(rows[0]["body"]) if rows else None

    def save_profile_approval(self, approval: ProfileApproval) -> None:
        self._write(
            "save profile approval",
            "INSERT INTO profile_approvals (approval_id, proposal_id, approval_json) "
            "VALUES (?, ?, ?)",
            (approval.approval_id, approval.proposal_id, approval.model_dump_json()),
        )

    def get_profile_approval(self, proposal_id: str) -> ProfileApproval | None:
        rows = self._read(
            "read profile approval",
            "SELECT approval_json AS body FROM profile_approvals WHERE proposal_id = ?",
            (proposal_id,),
        )
        return ProfileApproval.model_validate_json(rows[0]["body"]) if rows else None

    def save_profile_application(self, application: ProfileApplication) -> None:
        self._write(
            "save profile application",
            "INSERT INTO profile_applications "
            "(application_id, proposal_id, platform, result, application_json, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                application.application_id,
                application.proposal_id,
                application.platform,
                application.result.value,
                application.model_dump_json(),
                application.recorded_at.isoformat(),
            ),
        )

    def profile_applications(self, proposal_id: str) -> list[ProfileApplication]:
        rows = self._read(
            "list profile applications",
            "SELECT application_json AS body FROM profile_applications WHERE proposal_id = ? "
            "ORDER BY recorded_at",
            (proposal_id,),
        )
        return [ProfileApplication.model_validate_json(row["body"]) for row in rows]

    def _write(self, operation: str, sql: str, parameters: tuple[object, ...]) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(sql, parameters)
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _read(self, operation: str, sql: str, parameters: tuple[object, ...]) -> list[sqlite3.Row]:
        try:
            with self.database.connect() as connection:
                return list(connection.execute(sql, parameters).fetchall())
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _raise(self, operation: str, error: sqlite3.Error) -> Never:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
