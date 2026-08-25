"""Read-only job discovery backed by the external ``liepin-cli`` subprocess.

``liepin-cli`` (https://github.com/liepin-tech-2026/liepin-cil) is invoked as an
opaque process boundary; no code from that project is vendored here. Only its
read-only ``job search`` surface is reachable. ``job apply`` is deliberately not
wired up: delivery belongs to a separate connector boundary with its own
authorization and approval gates, and Job Intelligence must not reach it.
"""

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.schemas.job_intelligence import JobListing, JobSearchQuery

SOURCE_NAME = "liepin"

# Platform states that a human must clear. These are not transient transport
# faults, so they are never retried and never worked around.
_INTERVENTION_MARKERS = (
    "token",
    "unauthorized",
    "forbidden",
    "401",
    "403",
    "captcha",
    "verify",
    "登录",
    "未授权",
    "无权限",
    "验证码",
    "风控",
    "频繁",
)

# Upstream exits 1 for request failures (including 401/403) and 2 for everything
# else: a missing token, a browser that would not open, or invalid input.
_CONFIG_EXIT_CODE = 2

CommandRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _decode(raw: bytes) -> str:
    """Decode child output that may not be UTF-8.

    On a Windows console the upstream CLI writes its JSON in the legacy ANSI
    codepage (cp936/GBK) whenever stdout is a pipe, so decoding as UTF-8 alone
    would silently replace every Chinese character with U+FFFD.
    """
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _child_environment() -> dict[str, str]:
    # Ask the child to emit UTF-8 ; _decode still covers versions that ignore this.
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def _default_runner(command: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    # Fixed argv, never a shell string, so the command is not injectable.
    completed = subprocess.run(
        list(command),
        capture_output=True,
        timeout=120,
        check=False,
        env=_child_environment(),
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        _decode(completed.stdout),
        _decode(completed.stderr),
    )


def _first_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int | float):
            return str(value)
    return None


class LiepinCliJobSource:
    """Search Liepin listings through the local CLI, without delivery operations.

    Implements ``JobListingSource`` rather than ``JobDiscoverySource``: the upstream
    ``/mcp/search-job`` response carries no JD text, so this source cannot honestly
    produce a ``SourceJobRecord`` and must not fabricate one.
    """

    def __init__(
        self,
        *,
        executable: str = "liepin-cli",
        runner: CommandRunner | None = None,
    ) -> None:
        self._executable = executable
        self._runner = runner or _default_runner

    def search_listings(self, query: JobSearchQuery) -> list[JobListing]:
        command = [self._executable, "job", "search", "--output", "json"]
        job_name = query.title or query.query
        if job_name:
            command += ["--job-name", job_name]
        if query.location:
            command += ["--address", query.location]
        if query.company:
            command += ["--company-name", query.company]

        payload = self._invoke(command)
        collected_at = datetime.now(UTC)
        listings = [self._to_listing(item, collected_at) for item in _iter_jobs(payload)]
        if query.source_job_id is not None:
            listings = [item for item in listings if item.source_job_id == query.source_job_id]
        return listings

    def _invoke(self, command: Sequence[str]) -> Any:
        try:
            completed = self._runner(command)
        except FileNotFoundError as error:
            raise UserInterventionRequiredError(
                "liepin-cli is not installed or not on PATH.",
                details={"source": SOURCE_NAME, "executable": self._executable},
            ) from error
        except subprocess.TimeoutExpired as error:
            raise UserInterventionRequiredError(
                "liepin-cli did not respond in time.",
                details={"source": SOURCE_NAME},
            ) from error

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            self._raise_for_platform_state(stderr)
            if completed.returncode == _CONFIG_EXIT_CODE:
                # Upstream maps everything that is not a request failure to exit 2:
                # a missing token, a browser that would not open, or invalid input.
                # Its guidance text is only printed on an interactive terminal, so a
                # subprocess sees an empty stderr and must not guess from the text.
                raise UserInterventionRequiredError(
                    "liepin-cli needs setup or re-authorization before it can search.",
                    details={
                        "source": SOURCE_NAME,
                        "returncode": completed.returncode,
                        "stderr": stderr[:500],
                        "hint": "run `liepin-cli setup` in an interactive terminal",
                    },
                ) from None
            raise InvalidProviderOutputError(
                "liepin-cli exited with a failure.",
                details={
                    "source": SOURCE_NAME,
                    "returncode": completed.returncode,
                    "stderr": stderr[:500],
                },
            )

        stdout = (completed.stdout or "").strip()
        if not stdout:
            raise InvalidProviderOutputError(
                "liepin-cli returned no output.",
                details={"source": SOURCE_NAME},
            )
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as error:
            # Auth prompts are sometimes written to stdout instead of stderr.
            self._raise_for_platform_state(stdout)
            raise InvalidProviderOutputError(
                "liepin-cli returned output that is not valid JSON.",
                details={"source": SOURCE_NAME, "stdout": stdout[:500]},
            ) from error

    @staticmethod
    def _raise_for_platform_state(text: str) -> None:
        lowered = text.casefold()
        if any(marker in lowered for marker in _INTERVENTION_MARKERS):
            raise UserInterventionRequiredError(
                "Liepin requires the user to refresh authorization or clear a platform check.",
                details={"source": SOURCE_NAME, "detail": text[:500]},
            )

    @staticmethod
    def _to_listing(item: Mapping[str, Any], collected_at: datetime) -> JobListing:
        source_job_id = _first_text(item, "jobId", "job_id", "id", "encryptJobId")
        title = _first_text(item, "jobName", "job_name", "title", "name")
        company = _first_text(item, "company", "compName", "companyName", "comp_name")
        url = _first_text(item, "jobDetailUrl", "link", "url", "jobUrl", "href")

        missing = [
            name
            for name, value in (
                ("source_job_id", source_job_id),
                ("title", title),
                ("company", company),
                ("url", url),
            )
            if value is None
        ]
        if missing:
            raise InvalidProviderOutputError(
                "liepin-cli listing is missing required fields.",
                details={"source": SOURCE_NAME, "missing_fields": missing},
            )

        tags = item.get("companyTags")
        company_tags = (
            [str(tag) for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
        )

        try:
            return JobListing(
                source=SOURCE_NAME,
                source_job_id=source_job_id,  # type: ignore[arg-type]
                title=title,  # type: ignore[arg-type]
                company=company,  # type: ignore[arg-type]
                location=_first_text(item, "location", "address", "city", "dq"),
                url=url,  # type: ignore[arg-type]
                salary_text=_first_text(item, "salary", "salaryText", "compensation"),
                education=_first_text(item, "education", "eduLevel"),
                work_years=_first_text(item, "workYears", "workExperience"),
                industry=_first_text(item, "industry"),
                company_size=_first_text(item, "companySize"),
                financing_stage=_first_text(item, "financingStage"),
                company_tags=company_tags,
                collected_at=collected_at,
            )
        except ValidationError as error:
            raise InvalidProviderOutputError(
                "liepin-cli listing does not satisfy the listing contract.",
                details={"source": SOURCE_NAME, "source_job_id": source_job_id},
            ) from error


def _iter_jobs(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        candidates: Any = payload
    elif isinstance(payload, Mapping):
        for key in ("jobs", "data", "list", "records", "items", "result"):
            nested = payload.get(key)
            if isinstance(nested, list):
                candidates = nested
                break
            if isinstance(nested, Mapping):
                inner = nested.get("list") or nested.get("records") or nested.get("jobs")
                if isinstance(inner, list):
                    candidates = inner
                    break
        else:
            raise InvalidProviderOutputError(
                "liepin-cli response did not contain a job list.",
                details={"source": SOURCE_NAME, "keys": sorted(map(str, payload))},
            )
    else:
        raise InvalidProviderOutputError(
            "liepin-cli response was not a job list.",
            details={"source": SOURCE_NAME, "type": type(payload).__name__},
        )
    return [item for item in candidates if isinstance(item, Mapping)]
