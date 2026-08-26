import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.applications.approval import ApplicationApprovalService, compute_digests
from jobagent.applications.audit import ApplicationAuditor
from jobagent.errors import StorageError
from jobagent.schemas.applications import (
    ApplicationPackage,
    DeliveryPolicy,
    DeliveryResult,
    InterventionReason,
    SendResultStatus,
)
from jobagent.storage.application_repository import SqliteApplicationAuditRepository
from jobagent.storage.database import Database

from .conftest import FIXED_NOW, PackageFactory

POLICY = DeliveryPolicy()


def repository(tmp_path: Path) -> SqliteApplicationAuditRepository:
    database = Database(tmp_path / "jobagent.sqlite3")
    database.migrate()
    return SqliteApplicationAuditRepository(database)


def result(
    package: ApplicationPackage,
    status: SendResultStatus = SendResultStatus.SENT,
    **extra: object,
) -> DeliveryResult:
    return DeliveryResult(
        application_id=package.application_id,
        status=status,
        attempted_at=FIXED_NOW,
        **extra,  # type: ignore[arg-type]
    )


def auditor(tmp_path: Path) -> ApplicationAuditor:
    return ApplicationAuditor(repository(tmp_path), clock=lambda: FIXED_NOW)


def test_audit_records_identifiers_and_digests_only(
    package: ApplicationPackage,
    tmp_path: Path,
) -> None:
    digests = compute_digests(package, POLICY)
    approval = ApplicationApprovalService().approve(
        package,
        POLICY,
        confirmed=True,
        approved_at=datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
    )

    audit = auditor(tmp_path).record_attempt(
        package=package,
        digests=digests,
        approval=approval,
        result=result(package),
    )

    assert audit.audit_id == "AUDIT_ALPHA_001_0001"
    assert audit.job_id == "JOB_ALPHA_001"
    assert audit.platform == "mock-alpha"
    assert audit.resume_variant_id == "RESUME_ALPHA_V1"
    assert audit.resume_digest == digests.resume_digest
    assert audit.message_digest == digests.message_digest
    assert audit.approval_id == "APPROVAL_ALPHA_001"
    assert package.message not in audit.model_dump_json()
    assert package.resume_variant.items[0].text not in audit.model_dump_json()


def test_every_attempt_gets_its_own_increasing_record(
    package: ApplicationPackage,
    tmp_path: Path,
) -> None:
    service = auditor(tmp_path)
    digests = compute_digests(package, POLICY)

    for status in (
        SendResultStatus.FAILED,
        SendResultStatus.USER_INTERVENTION_REQUIRED,
        SendResultStatus.SENT,
    ):
        service.record_attempt(
            package=package,
            digests=digests,
            approval=None,
            result=result(package, status),
        )

    audits = service.list_audits("APP_ALPHA_001")
    assert [audit.attempt for audit in audits] == [1, 2, 3]
    assert [audit.result for audit in audits] == [
        SendResultStatus.FAILED,
        SendResultStatus.USER_INTERVENTION_REQUIRED,
        SendResultStatus.SENT,
    ]


def test_intervention_reason_survives_the_round_trip(
    package: ApplicationPackage,
    tmp_path: Path,
) -> None:
    service = auditor(tmp_path)
    service.record_attempt(
        package=package,
        digests=compute_digests(package, POLICY),
        approval=None,
        result=result(
            package,
            SendResultStatus.USER_INTERVENTION_REQUIRED,
            intervention_reason=InterventionReason.RISK_CONTROL,
        ),
    )

    stored = service.list_audits("APP_ALPHA_001")[0]
    assert stored.intervention_reason is InterventionReason.RISK_CONTROL


def test_audits_are_append_only(package: ApplicationPackage, tmp_path: Path) -> None:
    store = repository(tmp_path)
    service = ApplicationAuditor(store, clock=lambda: FIXED_NOW)
    audit = service.record_attempt(
        package=package,
        digests=compute_digests(package, POLICY),
        approval=None,
        result=result(package),
    )

    with pytest.raises(StorageError, match="append application audit"):
        store.append_audit(audit)


def test_audits_are_scoped_and_ordered(
    package_factory: PackageFactory,
    tmp_path: Path,
) -> None:
    service = auditor(tmp_path)
    for application_id in ("APP_BETA_002", "APP_ALPHA_001"):
        item = package_factory(application_id=application_id)
        service.record_attempt(
            package=item,
            digests=compute_digests(item, POLICY),
            approval=None,
            result=result(item),
        )

    assert [audit.application_id for audit in service.list_audits()] == [
        "APP_ALPHA_001",
        "APP_BETA_002",
    ]
    assert [audit.application_id for audit in service.list_audits("APP_BETA_002")] == [
        "APP_BETA_002"
    ]


def test_migration_creates_the_audit_table(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobagent.sqlite3")
    database.migrate()

    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert version == 3
    assert "application_audits" in tables


def test_audit_table_rejects_a_zero_attempt(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobagent.sqlite3")
    database.migrate()

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO application_audits (
                audit_id, application_id, attempt, result, audit_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("AUDIT_X_0000", "APP_X", 0, "sent", "{}", "now"),
        )
