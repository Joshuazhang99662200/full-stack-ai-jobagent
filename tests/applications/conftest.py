"""Synthetic delivery fixtures. No real resume, contact detail or platform payload."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from jobagent.applications.preview import ApplicationPreviewService
from jobagent.schemas.applications import (
    ApplicationAudit,
    ApplicationPackage,
    DeliveryResult,
    SendResultStatus,
)
from jobagent.schemas.common import ProvenanceRecord
from jobagent.schemas.jobs import MatchDecision, MatchResult, NormalizedJob
from jobagent.schemas.optimizer import (
    ClaimLedger,
    ClaimRecord,
    KeywordCoverageReport,
    OptimizedResumeItem,
    ResumeDiff,
    ResumeVariant,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)

FIXED_NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

JobFactory = Callable[..., NormalizedJob]
VariantFactory = Callable[..., ResumeVariant]
PackageFactory = Callable[..., ApplicationPackage]


def build_job(job_id: str = "JOB_ALPHA_001", *, title: str = "Python Engineer") -> NormalizedJob:
    return NormalizedJob(
        id=job_id,
        source="mock-alpha",
        source_job_id="alpha-001",
        title=title,
        company="Example Labs",
        location="Copenhagen",
        jd_raw="Build Python API services.",
        url="https://jobs.example.test/alpha-001",
        collected_at=datetime(2026, 8, 21, tzinfo=UTC),
        provenance=[
            ProvenanceRecord(
                source="mock-alpha",
                source_id="alpha-001",
                url="https://jobs.example.test/alpha-001",
                collected_at=datetime(2026, 8, 21, tzinfo=UTC),
            )
        ],
    )


def build_match() -> MatchResult:
    return MatchResult(
        overall=0.82,
        decision=MatchDecision.STRONG_MATCH,
        strengths=["Ships typed Python services"],
        evidence_ids=["EVID_001"],
    )


def build_variant(
    variant_id: str = "RESUME_ALPHA_V1",
    *,
    job_id: str = "JOB_ALPHA_001",
    passed: bool = True,
    text: str = "Delivered a typed Python API used by three internal teams.",
    generated_at: datetime = datetime(2026, 8, 25, tzinfo=UTC),
) -> ResumeVariant:
    report = (
        VerificationReport(passed=True, evidence_coverage=1.0)
        if passed
        else VerificationReport(
            passed=False,
            unsupported_claims=1,
            evidence_coverage=0.5,
            issues=[
                VerificationIssue(
                    code="UNSUPPORTED_CLAIM",
                    message="No evidence backs the throughput number.",
                    claim_id="CLAIM_001",
                )
            ],
        )
    )
    return ResumeVariant(
        id=variant_id,
        target_job_id=job_id,
        target_role="Python Engineer",
        selected_evidence_ids=["EVID_001"],
        items=[
            OptimizedResumeItem(
                id="ITEM_001",
                section="experience",
                text=text,
                evidence_ids=["EVID_001"],
            )
        ],
        claim_ledger=ClaimLedger(
            claims=[
                ClaimRecord(
                    claim_id="CLAIM_001",
                    resume_item_id="ITEM_001",
                    text=text,
                    claim_type="delivery",
                    evidence_ids=["EVID_001"],
                    verification_status=(
                        VerificationStatus.SUPPORTED if passed else VerificationStatus.UNSUPPORTED
                    ),
                )
            ]
        ),
        keyword_coverage=KeywordCoverageReport(supported_exact=["python"]),
        verification=report,
        diff=ResumeDiff(),
        prompt_bundle_digest="sha256:prompt-bundle",
        generated_at=generated_at,
    )


def build_package(
    *,
    application_id: str = "APP_ALPHA_001",
    message: str = "Hello, I would like to apply for the Python Engineer role.",
    variant: ResumeVariant | None = None,
    job: NormalizedJob | None = None,
    prepared_at: datetime = FIXED_NOW,
) -> ApplicationPackage:
    return ApplicationPreviewService().prepare(
        application_id=application_id,
        job=job if job is not None else build_job(),
        match=build_match(),
        resume_variant=variant if variant is not None else build_variant(),
        message=message,
        prepared_at=prepared_at,
    )


class RecordingDeliverySource:
    """Test double. Every call is recorded so batching and retries stay observable."""

    def __init__(
        self,
        *,
        result: DeliveryResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def submit_application(self, package: ApplicationPackage) -> DeliveryResult:
        self.calls.append(package.application_id)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return DeliveryResult(
            application_id=package.application_id,
            status=SendResultStatus.SENT,
            attempted_at=FIXED_NOW,
            external_reference="EXT-1",
        )


class InMemoryAuditRepository:
    """Audit port double with append-only semantics."""

    def __init__(self) -> None:
        self.audits: list[ApplicationAudit] = []

    def append_audit(self, audit: ApplicationAudit) -> None:
        self.audits.append(audit)

    def next_attempt(self, application_id: str) -> int:
        return 1 + sum(1 for item in self.audits if item.application_id == application_id)

    def list_audits(self, application_id: str | None = None) -> Sequence[ApplicationAudit]:
        if application_id is None:
            return tuple(self.audits)
        return tuple(item for item in self.audits if item.application_id == application_id)


@pytest.fixture
def fixed_now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def clock() -> Callable[[], datetime]:
    return lambda: FIXED_NOW


@pytest.fixture
def job_factory() -> JobFactory:
    return build_job


@pytest.fixture
def variant_factory() -> VariantFactory:
    return build_variant


@pytest.fixture
def package_factory() -> PackageFactory:
    return build_package


@pytest.fixture
def package(package_factory: PackageFactory) -> ApplicationPackage:
    return package_factory()


@pytest.fixture
def audit_repository() -> InMemoryAuditRepository:
    return InMemoryAuditRepository()


@pytest.fixture
def delivery_source() -> RecordingDeliverySource:
    return RecordingDeliverySource()
