"""Submit one approved application to Liepin through its official CLI.

This is the delivery boundary, kept deliberately separate from discovery: it is
reached only after `DeliveryGate` has re-verified the human approval against the
exact artifacts. Nothing here decides whether to send — it only performs a send
that a person already authorized.

`liepin-cli` is invoked as an opaque process, the same way discovery does. Login,
CAPTCHA, verification, risk control and rate limiting all become
`USER_INTERVENTION_REQUIRED`: the caller hands control back to the person rather
than retrying, rotating accounts or slowing down to probe the limit.

The port has no plural operation, and neither does this class.
"""

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.applications import (
    ApplicationPackage,
    DeliveryResult,
    InterventionReason,
    SendResultStatus,
)

SOURCE_NAME = "liepin"

# Upstream requires jobKind and states it must equal the value the search result
# carried. Guessing between "1" (headhunter posting) and "2" (direct) could apply
# to a different posting than the one that was reviewed.
_VALID_JOB_KINDS = ("1", "2")

_INTERVENTION_PATTERNS: tuple[tuple[str, InterventionReason], ...] = (
    ("captcha", InterventionReason.CAPTCHA_REQUIRED),
    ("验证码", InterventionReason.CAPTCHA_REQUIRED),
    ("登录", InterventionReason.LOGIN_REQUIRED),
    ("unauthorized", InterventionReason.LOGIN_REQUIRED),
    ("401", InterventionReason.LOGIN_REQUIRED),
    ("token", InterventionReason.LOGIN_REQUIRED),
    ("403", InterventionReason.RISK_CONTROL),
    ("风控", InterventionReason.RISK_CONTROL),
    ("频繁", InterventionReason.RISK_CONTROL),
    ("too many requests", InterventionReason.RISK_CONTROL),
    ("429", InterventionReason.RISK_CONTROL),
)

CommandRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[bytes]"]


def _default_runner(command: Sequence[str]) -> "subprocess.CompletedProcess[bytes]":
    # Fixed argv, never a shell string, so the command is not injectable.
    return subprocess.run(list(command), capture_output=True, timeout=120, check=False)


def _decode(raw: bytes) -> str:
    """Upstream emits the Windows ANSI code page when stdout is a pipe."""
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class LiepinCliDeliverySource:
    """Deliver exactly one approved application through `liepin-cli job apply`."""

    def __init__(
        self,
        *,
        executable: str = "liepin-cli",
        runner: CommandRunner | None = None,
    ) -> None:
        self._executable = executable
        self._runner = runner or _default_runner

    def submit_application(self, package: ApplicationPackage) -> DeliveryResult:
        job = package.job
        if job.source != SOURCE_NAME:
            raise ContractValidationError(
                "This delivery source only handles Liepin applications.",
                details={"source": job.source, "expected": SOURCE_NAME},
            )
        job_kind = self._required_job_kind(package)

        command = [
            self._executable,
            "job",
            "apply",
            "--job-id",
            job.source_job_id,
            "--job-kind",
            job_kind,
            "--output",
            "json",
        ]
        return self._invoke(command, package)

    @staticmethod
    def _required_job_kind(package: ApplicationPackage) -> str:
        job_kind = package.job.job_kind
        if job_kind is None:
            raise ContractValidationError(
                "This posting carries no job kind, and it must not be guessed. "
                "Re-run discovery so the value comes from the search result.",
                details={
                    "source": SOURCE_NAME,
                    "application_id": package.application_id,
                    "job_id": package.job.id,
                },
            )
        if job_kind not in _VALID_JOB_KINDS:
            raise ContractValidationError(
                "The posting's job kind is not one the platform accepts.",
                details={
                    "source": SOURCE_NAME,
                    "job_kind": job_kind,
                    "accepted": list(_VALID_JOB_KINDS),
                },
            )
        return job_kind

    def _invoke(self, command: Sequence[str], package: ApplicationPackage) -> DeliveryResult:
        attempted_at = datetime.now(UTC)
        try:
            completed = self._runner(command)
        except FileNotFoundError as error:
            raise UserInterventionRequiredError(
                "liepin-cli is not installed or not on PATH.",
                details={"source": SOURCE_NAME, "executable": self._executable},
            ) from error
        except subprocess.TimeoutExpired:
            # A timed-out submit may or may not have landed. Never resend blindly:
            # a person has to check the platform before any second attempt.
            return DeliveryResult(
                application_id=package.application_id,
                status=SendResultStatus.USER_INTERVENTION_REQUIRED,
                attempted_at=attempted_at,
                intervention_reason=InterventionReason.PLATFORM_CHANGED,
                failure_reason=(
                    "liepin-cli did not respond in time; confirm on the platform "
                    "whether the application was submitted before trying again."
                ),
            )

        stdout = _decode(completed.stdout or b"").strip()
        stderr = _decode(completed.stderr or b"").strip()

        if completed.returncode != 0:
            reason = self._intervention_reason(f"{stderr}\n{stdout}")
            if reason is not None:
                return DeliveryResult(
                    application_id=package.application_id,
                    status=SendResultStatus.USER_INTERVENTION_REQUIRED,
                    attempted_at=attempted_at,
                    intervention_reason=reason,
                    failure_reason=stderr[:500] or None,
                )
            if completed.returncode == 2:
                # Upstream prints nothing here when stderr is not a terminal.
                return DeliveryResult(
                    application_id=package.application_id,
                    status=SendResultStatus.USER_INTERVENTION_REQUIRED,
                    attempted_at=attempted_at,
                    intervention_reason=InterventionReason.LOGIN_REQUIRED,
                    failure_reason="liepin-cli exited 2; run `liepin-cli setup` to authorize.",
                )
            return DeliveryResult(
                application_id=package.application_id,
                status=SendResultStatus.FAILED,
                attempted_at=attempted_at,
                failure_reason=stderr[:500] or f"liepin-cli exited {completed.returncode}",
            )

        return DeliveryResult(
            application_id=package.application_id,
            status=SendResultStatus.SENT,
            attempted_at=attempted_at,
            external_reference=self._external_reference(stdout, package),
        )

    @staticmethod
    def _intervention_reason(text: str) -> InterventionReason | None:
        lowered = text.casefold()
        for marker, reason in _INTERVENTION_PATTERNS:
            if marker in lowered:
                return reason
        return None

    @staticmethod
    def _external_reference(stdout: str, package: ApplicationPackage) -> str:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return package.job.source_job_id
        if isinstance(payload, dict):
            for key in ("applyId", "id", "recordId", "data"):
                value = payload.get(key)
                if isinstance(value, str | int):
                    return str(value)
        return package.job.source_job_id
