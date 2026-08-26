"""Ports owned by the human-approved delivery subsystem.

No implementation of ``ApplicationDeliverySource`` ships with JobAgent. Wiring a
real platform is a separate change that must satisfy
`skills/job-hunting/references/connector-contract.md`.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jobagent.schemas.applications import ApplicationAudit, ApplicationPackage, DeliveryResult


@runtime_checkable
class ApplicationDeliverySource(Protocol):
    """Submit exactly one already-approved application.

    Implementations translate login, CAPTCHA, verification, risk control, rate
    limiting and platform changes into ``UserInterventionRequiredError`` (or a
    ``USER_INTERVENTION_REQUIRED`` result) and hand control back to the person.
    They never retry, never rotate accounts or proxies, and never accept a batch:
    the port deliberately has no plural operation to call.
    """

    def submit_application(self, package: ApplicationPackage) -> DeliveryResult: ...


@runtime_checkable
class ApplicationAuditRepository(Protocol):
    """Append-only record of every delivery attempt, successful or not."""

    def append_audit(self, audit: ApplicationAudit) -> None: ...

    def next_attempt(self, application_id: str) -> int: ...

    def list_audits(self, application_id: str | None = None) -> Sequence[ApplicationAudit]: ...
