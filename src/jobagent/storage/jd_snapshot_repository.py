"""Append-only JD content, discoveries and derived feature versions."""

import json
import sqlite3
from datetime import UTC, datetime

from jobagent.errors import ContractValidationError, StorageError
from jobagent.jobs.jd_snapshot import canonical_digest, make_snapshot, snapshot_content_digest
from jobagent.jobs.lexicon import lexicon_digest, serialize_lexicon
from jobagent.schemas.jd_snapshot import (
    JDSnapshot,
    JDSnapshotInput,
    SnapshotCaptureResult,
    SnapshotDiscovery,
)
from jobagent.schemas.lexicon import CombinationPlan, CombinationRequest, JDFeatureSet, Lexicon
from jobagent.storage.database import Database


class SqliteJDSnapshotRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _get(connection: sqlite3.Connection, snapshot_id: str) -> JDSnapshot:
        row = connection.execute(
            "SELECT snapshot_json FROM jd_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("JD snapshot not found.")
        return JDSnapshot.model_validate_json(row["snapshot_json"])

    def get(self, snapshot_id: str) -> JDSnapshot:
        with self.database.connect() as connection:
            return self._get(connection, snapshot_id)

    def capture(self, request: JDSnapshotInput) -> SnapshotCaptureResult:
        fingerprint = canonical_digest(request.model_dump(mode="json"))
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                old = connection.execute(
                    "SELECT * FROM jd_discoveries WHERE observation_id = ?",
                    (request.observation_id,),
                ).fetchone()
                if old is not None:
                    if old["input_digest"] != fingerprint:
                        raise ContractValidationError("Observation ID has different content.")
                    return SnapshotCaptureResult(
                        snapshot=self._get(connection, old["snapshot_id"]),
                        discovery=SnapshotDiscovery.model_validate_json(old["discovery_json"]),
                        created=False,
                    )
                row = connection.execute(
                    "SELECT snapshot_json FROM jd_snapshots WHERE job_id = ? "
                    "ORDER BY snapshot_version DESC LIMIT 1",
                    (request.job_id,),
                ).fetchone()
                latest = (
                    None if row is None else JDSnapshot.model_validate_json(row["snapshot_json"])
                )
                changed = latest is None or latest.content_digest != snapshot_content_digest(
                    request
                )
                if latest is not None and changed and request.fetched_at < latest.fetched_at:
                    raise ContractValidationError("Older capture cannot replace the current JD.")
                snapshot = (
                    make_snapshot(
                        request,
                        1 if latest is None else latest.snapshot_version + 1,
                    )
                    if changed
                    else latest
                )
                assert snapshot is not None
                if changed:
                    connection.execute(
                        "INSERT INTO jd_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            snapshot.snapshot_id,
                            snapshot.job_id,
                            snapshot.snapshot_version,
                            snapshot.fetched_at.isoformat(),
                            snapshot.content_digest,
                            snapshot.model_dump_json(),
                        ),
                    )
                discovery = SnapshotDiscovery(
                    observation_id=request.observation_id,
                    snapshot_id=snapshot.snapshot_id,
                    job_id=request.job_id,
                    fetched_at=request.fetched_at,
                    query_hit=request.query_hit,
                    discovery_kind=request.discovery_kind,
                )
                connection.execute(
                    "INSERT INTO jd_discoveries VALUES (?, ?, ?, ?, ?)",
                    (
                        request.observation_id,
                        snapshot.snapshot_id,
                        request.job_id,
                        fingerprint,
                        discovery.model_dump_json(),
                    ),
                )
                return SnapshotCaptureResult(
                    snapshot=snapshot, discovery=discovery, created=changed
                )
        except sqlite3.Error as error:
            raise StorageError("JD snapshot ledger unavailable.") from error

    def list_snapshots(self, job_id: str) -> list[JDSnapshot]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT snapshot_json FROM jd_snapshots WHERE job_id = ? ORDER BY snapshot_version",
                (job_id,),
            ).fetchall()
        return [JDSnapshot.model_validate_json(row["snapshot_json"]) for row in rows]

    def discoveries(self, job_id: str) -> list[SnapshotDiscovery]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT discovery_json FROM jd_discoveries WHERE job_id = ? ORDER BY rowid",
                (job_id,),
            ).fetchall()
        return [SnapshotDiscovery.model_validate_json(row["discovery_json"]) for row in rows]

    def save_features(self, features: JDFeatureSet, lexicon_digest: str) -> str:
        snapshot = self.get(features.snapshot_id)
        if (features.job_id, features.snapshot_version, features.jd_text_hash) != (
            snapshot.job_id,
            snapshot.snapshot_version,
            snapshot.jd_text_hash,
        ):
            raise ContractValidationError("Features belong to a different snapshot.")

        if (features.company, features.fetched_at, features.completeness) != (
            snapshot.company,
            snapshot.fetched_at,
            snapshot.completeness,
        ):
            raise ContractValidationError("Feature metadata does not match the original snapshot.")
        if snapshot.completeness != "full" and features.features:
            raise ContractValidationError("Incomplete snapshots cannot contribute features.")
        if any(snapshot.jd_text[f.start : f.end] != f.evidence for f in features.features):
            raise ContractValidationError("Feature evidence is not present in the snapshot.")
        feature_id = canonical_digest([lexicon_digest, features.model_dump(mode="json")])
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT OR IGNORE INTO jd_feature_sets VALUES (?, ?, ?, ?, ?)",
                    (
                        feature_id,
                        features.snapshot_id,
                        lexicon_digest,
                        features.model_dump_json(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except sqlite3.Error as error:
            raise StorageError("Feature ledger unavailable.") from error
        return feature_id

    def feature_sets(self, snapshot_ids: list[str] | None = None) -> list[JDFeatureSet]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT feature_json FROM jd_feature_sets WHERE rowid IN "
                "(SELECT MAX(rowid) FROM jd_feature_sets GROUP BY snapshot_id) ORDER BY rowid",
            ).fetchall()
        values = [JDFeatureSet.model_validate_json(row["feature_json"]) for row in rows]
        return (
            values
            if snapshot_ids is None
            else [value for value in values if value.snapshot_id in snapshot_ids]
        )

    def save_lexicon(self, candidate_id: str, lexicon: Lexicon) -> str:
        digest = lexicon_digest(lexicon)
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT OR IGNORE INTO jd_lexicon_versions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        candidate_id,
                        digest,
                        lexicon.domain,
                        lexicon.model_dump_json(),
                        serialize_lexicon(lexicon),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except sqlite3.Error as error:
            raise StorageError("Lexicon version ledger unavailable.") from error
        return digest

    def get_lexicon(self, candidate_id: str, version_digest: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT lexicon_json, markdown_text FROM jd_lexicon_versions "
                "WHERE candidate_id = ? AND version_digest = ?",
                (candidate_id, version_digest),
            ).fetchone()
        if row is None:
            raise ContractValidationError("Private lexicon version not found for this candidate.")
        return {
            "lexicon": Lexicon.model_validate_json(row["lexicon_json"]).model_dump(mode="json"),
            "markdown": row["markdown_text"],
            "version_digest": version_digest,
        }

    def save_plan(
        self, lexicon: Lexicon, request: CombinationRequest, plan: CombinationPlan
    ) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT OR IGNORE INTO jd_query_plans VALUES (?, ?, ?, ?, ?)",
                    (
                        plan.version,
                        request.candidate_id,
                        request.source,
                        json.dumps(
                            {
                                "lexicon": lexicon.model_dump(mode="json"),
                                "request": request.model_dump(mode="json"),
                            },
                            ensure_ascii=False,
                        ),
                        plan.model_dump_json(),
                    ),
                )
        except sqlite3.Error as error:
            raise StorageError("Query plan ledger unavailable.") from error

    def get_plan(self, plan_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT input_json, plan_json FROM jd_query_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            raise ContractValidationError("Private query plan not found.")
        return {"input": json.loads(row["input_json"]), "plan": json.loads(row["plan_json"])}
