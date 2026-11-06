"""Manual Liepin handover until approved custom artifacts can be transmitted.

Upstream job apply only carries job ID/kind and uses the online resume. It cannot
fulfill an approval bound to a tailored attachment and message, so every package
is handed back to the person before any platform action.
"""

from datetime import UTC, datetime

from jobagent.errors import ContractValidationError
from jobagent.schemas.applications import (
    ApplicationPackage,
    DeliveryResult,
    InterventionReason,
    SendResultStatus,
)

SOURCE_NAME = "liepin"


class LiepinCliDeliverySource:
    """Refuse submission when custom artifact transmission is unavailable."""

    supports_custom_artifacts = False

    def submit_application(self, package: ApplicationPackage) -> DeliveryResult:
        if package.job.source != SOURCE_NAME:
            raise ContractValidationError("This delivery source only handles Liepin applications.")
        return DeliveryResult(
            application_id=package.application_id,
            status=SendResultStatus.USER_INTERVENTION_REQUIRED,
            attempted_at=datetime.now(UTC),
            intervention_reason=InterventionReason.PLATFORM_CHANGED,
            failure_reason=(
                "This connector cannot transmit the approved tailored attachment and message. "
                "No platform submission was attempted. Open the posting, manually attach the "
                "reviewed PDF and send the approved message; then verify the actual result."
            ),
        )
