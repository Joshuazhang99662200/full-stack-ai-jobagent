from datetime import UTC, datetime

from jobagent.schemas.applications import ApprovalRecord


def test_approval_binds_every_reviewed_artifact() -> None:
    approval = ApprovalRecord(
        application_id="APP_001",
        job_digest="sha256:job",
        resume_digest="sha256:resume",
        message_digest="sha256:message",
        policy_digest="sha256:policy",
        approved_at=datetime.now(UTC),
        approved_by="human",
    )
    assert approval.resume_digest == "sha256:resume"


def test_changed_resume_invalidates_approval() -> None:
    approval = ApprovalRecord(
        application_id="APP_001",
        job_digest="sha256:job",
        resume_digest="sha256:v1",
        message_digest="sha256:message",
        policy_digest="sha256:policy",
        approved_at=datetime.now(UTC),
        approved_by="human",
    )
    assert not approval.matches(
        job_digest="sha256:job",
        resume_digest="sha256:v2",
        message_digest="sha256:message",
        policy_digest="sha256:policy",
    )
