"""Read actual attempt outcomes; generated artifacts never imply delivery."""

from collections.abc import Sequence
from typing import Literal

from jobagent.schemas.applications import ApplicationAudit, ApplicationPackage, SendResultStatus
from jobagent.schemas.harness import ApplicationOutcome, HarnessReport


def build_report(
    run_id: str,
    packages: Sequence[ApplicationPackage],
    audits: Sequence[ApplicationAudit],
) -> HarnessReport:
    outcomes = []
    for package in packages:
        attempts = [a for a in audits if a.application_id == package.application_id]
        latest = max(attempts, key=lambda a: a.attempt) if attempts else None
        status: Literal["unknown", "simulated", "sent", "failed", "user_intervention_required"]
        if latest is None:
            status = "unknown"
        elif latest.result is SendResultStatus.SENT and latest.platform.startswith("mock"):
            status = "simulated"
        else:
            status = latest.result.value
        outcomes.append(
            ApplicationOutcome(
                application_id=package.application_id,
                job_id=package.job.id,
                status=status,
                attempts=len(attempts),
            )
        )
    return HarnessReport(run_id=run_id, outcomes=outcomes)
