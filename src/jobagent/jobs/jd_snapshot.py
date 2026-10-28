"""Pure raw-text snapshot construction; no normalization or I/O."""

import hashlib
import json

from jobagent.schemas.jd_snapshot import JDSnapshot, JDSnapshotInput
from jobagent.schemas.job_intelligence import SourceJobRecord


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_digest(value: object) -> str:
    return text_digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def snapshot_content_digest(request: JDSnapshotInput) -> str:
    return canonical_digest(
        request.model_dump(
            mode="json",
            exclude={
                "observation_id",
                "fetched_at",
                "query_hit",
                "discovery_kind",
            },
        )
    )


def make_snapshot(request: JDSnapshotInput, version: int) -> JDSnapshot:
    digest = snapshot_content_digest(request)
    identity = canonical_digest([request.job_id, version, digest])
    return JDSnapshot(
        **request.model_dump(exclude={"schema_version"}),
        snapshot_id="JSNAP_" + identity.removeprefix("sha256:")[:24].upper(),
        jd_text_hash=text_digest(request.jd_text),
        content_digest=digest,
        snapshot_version=version,
    )


def capture_from_record(record: SourceJobRecord, job_id: str) -> JDSnapshotInput:
    data = record.model_dump(mode="json")
    return JDSnapshotInput(
        observation_id="OBS_" + canonical_digest(data).removeprefix("sha256:")[:24].upper(),
        job_id=job_id,
        job_url=record.url,
        platform=record.source,
        fetched_at=record.collected_at,
        query_hit=record.search_term.strip()
        if record.search_term and record.search_term.strip()
        else None,
        discovery_kind="search" if record.search_term and record.search_term.strip() else "unknown",
        title=record.title,
        company=record.company,
        location=record.location,
        salary_raw=record.salary_text,
        jd_text=record.jd_raw,
        completeness="full",
    )
