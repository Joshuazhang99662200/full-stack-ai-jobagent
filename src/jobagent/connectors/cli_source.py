"""Drive any declared external CLI as an opaque job-listing subprocess.

Behaviour comes from a `SourceManifest`, so a new CLI-backed board is a YAML file
rather than a new class. Nothing here is specific to one platform.

The subprocess boundary is deliberate: no upstream code is vendored, and only the
read-only search surface a manifest declares is ever invoked. A manifest cannot
express delivery — there is no code path here that could run one.
"""

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.schemas.job_intelligence import JobListing, JobSearchQuery
from jobagent.schemas.sources import SourceManifest

CommandRunner = Callable[[Sequence[str], int], "subprocess.CompletedProcess[bytes]"]

_IDENTIFYING_FIELDS = ("source_job_id", "title", "company", "url")
_OPTIONAL_FIELDS = (
    "location",
    "salary_text",
    "education",
    "work_years",
    "industry",
    "company_size",
    "financing_stage",
    # Passes through the same manifest-declared mapping as every other field, so
    # a source that does not publish a job kind simply yields `None` here.
    "job_kind",
)


def _default_runner(command: Sequence[str], timeout: int) -> "subprocess.CompletedProcess[bytes]":
    # Fixed argv, never a shell string, so the command is not injectable.
    return subprocess.run(list(command), capture_output=True, timeout=timeout, check=False)


def _decode(raw: bytes) -> str:
    """Decode subprocess output, tolerating a legacy Windows ANSI code page.

    Some CLIs emit the console code page (cp936) when stdout is a pipe rather than
    a terminal. Decoding that as UTF-8 turns every CJK character into U+FFFD.
    """
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _first_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return str(value)
    return None


class CliListingSource:
    """Search a declared CLI-backed board without exposing delivery operations."""

    def __init__(
        self,
        manifest: SourceManifest,
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        if manifest.listing is None:
            raise InvalidProviderOutputError(
                "This source declares no CLI listing route.",
                details={"source": manifest.id},
            )
        self._manifest = manifest
        self._spec = manifest.listing
        self._runner = runner or _default_runner

    def search_listings(self, query: JobSearchQuery) -> list[JobListing]:
        command = list(self._spec.command)
        for field_name, flag in self._spec.query_options.items():
            value = getattr(query, field_name, None)
            if field_name == "query" and not value:
                value = query.title
            if value:
                command += [flag, str(value)]

        payload = self._invoke(command)
        collected_at = datetime.now(UTC)
        listings = [self._to_listing(item, collected_at) for item in self._iter_jobs(payload)]
        if query.source_job_id is not None:
            listings = [item for item in listings if item.source_job_id == query.source_job_id]
        return listings

    def _invoke(self, command: Sequence[str]) -> Any:
        source = self._manifest.id
        try:
            completed = self._runner(command, self._spec.timeout_seconds)
        except FileNotFoundError as error:
            raise UserInterventionRequiredError(
                f"{command[0]} is not installed or not on PATH.",
                details={"source": source, "executable": command[0]},
            ) from error
        except subprocess.TimeoutExpired as error:
            raise UserInterventionRequiredError(
                f"{command[0]} did not respond in time.",
                details={"source": source},
            ) from error

        stdout = _decode(completed.stdout or b"").strip()
        stderr = _decode(completed.stderr or b"").strip()

        if completed.returncode != 0:
            self._raise_for_platform_state(stderr or stdout, completed.returncode)
            # Exit codes other than 1 conventionally mean the tool never ran its
            # request; upstreams often print nothing when stderr is not a terminal.
            if completed.returncode != 1:
                raise UserInterventionRequiredError(
                    f"{command[0]} exited without running the request.",
                    details={
                        "source": source,
                        "returncode": completed.returncode,
                        "hint": f"Run `{command[0]} setup` in an interactive terminal.",
                    },
                )
            raise InvalidProviderOutputError(
                f"{command[0]} exited with a failure.",
                details={"source": source, "returncode": 1, "stderr": stderr[:500]},
            )

        if not stdout:
            raise InvalidProviderOutputError(
                f"{command[0]} returned no output.",
                details={"source": source},
            )
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as error:
            self._raise_for_platform_state(stdout, completed.returncode)
            raise InvalidProviderOutputError(
                f"{command[0]} returned output that is not valid JSON.",
                details={"source": source, "stdout": stdout[:500]},
            ) from error

    def _raise_for_platform_state(self, text: str, returncode: int) -> None:
        lowered = text.casefold()
        marker = next(
            (item for item in self._spec.intervention_markers if item.casefold() in lowered),
            None,
        )
        if marker is not None:
            raise UserInterventionRequiredError(
                "The platform needs the user to refresh authorization or clear a check.",
                details={
                    "source": self._manifest.id,
                    "marker": marker,
                    "returncode": returncode,
                    "detail": text[:500],
                },
            )

    def _iter_jobs(self, payload: Any) -> list[Mapping[str, Any]]:
        candidates = _unwrap(payload, self._spec.envelope_keys, self._manifest.id)
        return [item for item in candidates if isinstance(item, Mapping)]

    def _to_listing(self, item: Mapping[str, Any], collected_at: datetime) -> JobListing:
        values = {
            name: _first_text(item, self._spec.field_map.get(name, []))
            for name in (*_IDENTIFYING_FIELDS, *_OPTIONAL_FIELDS)
        }
        missing = [name for name in _IDENTIFYING_FIELDS if values[name] is None]
        if missing:
            raise InvalidProviderOutputError(
                "A listing is missing required fields.",
                details={"source": self._manifest.id, "missing_fields": missing},
            )

        tags = item.get("companyTags")
        company_tags = (
            [str(tag) for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
        )
        try:
            return JobListing(
                source=self._manifest.id,
                company_tags=company_tags,
                collected_at=collected_at,
                **values,  # type: ignore[arg-type]
            )
        except ValidationError as error:
            raise InvalidProviderOutputError(
                "A listing does not satisfy the listing contract.",
                details={"source": self._manifest.id, "source_job_id": values["source_job_id"]},
            ) from error


def _unwrap(payload: Any, envelope_keys: Sequence[str], source: str) -> Any:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in envelope_keys:
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, Mapping):
                inner = _unwrap_shallow(nested, envelope_keys)
                if inner is not None:
                    return inner
        raise InvalidProviderOutputError(
            "The response did not contain a job list.",
            details={"source": source, "keys": sorted(map(str, payload))},
        )
    raise InvalidProviderOutputError(
        "The response was not a job list.",
        details={"source": source, "type": type(payload).__name__},
    )


def _unwrap_shallow(payload: Mapping[str, Any], envelope_keys: Sequence[str]) -> list[Any] | None:
    for key in envelope_keys:
        nested = payload.get(key)
        if isinstance(nested, list):
            return nested
    return None
