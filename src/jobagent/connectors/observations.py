"""Shared validation of untrusted host observations against source manifests."""

from collections.abc import Mapping

from pydantic import ValidationError

from jobagent.connectors.extraction import MIN_JD_LENGTH
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.sources import SourceKind, SourceManifest


def check_observation(
    item: object, known: Mapping[str, SourceManifest]
) -> tuple[str, SourceJobRecord | None]:
    try:
        record = SourceJobRecord.model_validate(item)
    except ValidationError:
        return "invalid_record", None
    manifest = known.get(record.source)
    spec = manifest.host_browser if manifest is not None else None
    if spec is None:
        return "no_host_route", None
    if record.access_state not in {"public", "authenticated"}:
        return "access_unavailable", None
    if record.completeness != "full":
        return "incomplete_jd", None
    prefixes = spec.detail_url_prefixes
    if record.capture_kind == "panel":
        if not record.panel_locator or record.panel_source_job_id != record.source_job_id:
            return "panel_identity_missing", None
        prefixes = spec.panel_url_prefixes
    if not any(str(record.url).startswith(prefix) for prefix in prefixes):
        return "url_outside_board", None
    if len(record.jd_raw.strip()) < MIN_JD_LENGTH:
        return "jd_too_short", None
    if any(marker in record.jd_raw for marker in spec.stop_markers):
        return "gate_page", None
    if (not record.read_attempt_id and manifest is not None
            and manifest.kind is not SourceKind.FIXTURE):
        return "read_attempt_missing", None
    return "", record
