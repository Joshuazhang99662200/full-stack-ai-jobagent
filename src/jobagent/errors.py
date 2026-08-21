"""Stable domain failures shared by JobAgent capabilities."""

from collections.abc import Mapping
from typing import Any, ClassVar


class JobAgentError(Exception):
    """Base error with a machine-readable code and structured details."""

    code: ClassVar[str] = "JOBAGENT_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class ContractValidationError(JobAgentError):
    code = "CONTRACT_VALIDATION_ERROR"


class MissingEvidenceError(JobAgentError):
    code = "MISSING_EVIDENCE"


class EvidenceConflictError(JobAgentError):
    code = "EVIDENCE_CONFLICT"


class PolicyRejectionError(JobAgentError):
    code = "POLICY_REJECTION"


class UserInterventionRequiredError(JobAgentError):
    code = "USER_INTERVENTION_REQUIRED"


class InvalidProviderOutputError(JobAgentError):
    code = "INVALID_PROVIDER_OUTPUT"


class StaleApprovalError(JobAgentError):
    code = "STALE_APPROVAL"


class StorageError(JobAgentError):
    code = "STORAGE_ERROR"


class ResumeParseError(JobAgentError):
    code = "RESUME_PARSE_ERROR"


class JobNotFoundError(JobAgentError):
    code = "JOB_NOT_FOUND"
