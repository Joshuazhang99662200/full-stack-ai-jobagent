"""Tell profile versions apart from the snapshots a patrol keeps."""

import hashlib
import json
from collections.abc import Sequence

from jobagent.schemas.profile import ProfileField, ProfileSnapshot, ProfileVersion


def profile_digest(fields: Sequence[ProfileField]) -> str:
    """The same sections with the same words give the same digest, in any order."""
    canonical = json.dumps(
        sorted((field.name, field.text) for field in fields),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _changed(before: ProfileSnapshot, after: ProfileSnapshot) -> list[str]:
    old = {field.name: field.text for field in before.fields}
    new = {field.name: field.text for field in after.fields}
    return sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))


def next_profile_version(
    current: ProfileVersion | None,
    current_snapshot: ProfileSnapshot | None,
    snapshot: ProfileSnapshot,
) -> ProfileVersion | None:
    """The version this snapshot opens, or None when the profile did not change."""
    if current is not None and current.digest == snapshot.digest:
        return None
    seed = f"{snapshot.platform}|{snapshot.snapshot_id}".encode()
    version_id = f"PROFVER_{hashlib.sha256(seed).hexdigest()[:16].upper()}"
    if current is None or current_snapshot is None:
        return ProfileVersion(
            version_id=version_id,
            platform=snapshot.platform,
            digest=snapshot.digest,
            effective_at=snapshot.captured_at,
            snapshot_id=snapshot.snapshot_id,
            origin="baseline",
        )
    return ProfileVersion(
        version_id=version_id,
        platform=snapshot.platform,
        digest=snapshot.digest,
        effective_at=snapshot.captured_at,
        snapshot_id=snapshot.snapshot_id,
        origin="external",
        changed_fields=_changed(current_snapshot, snapshot),
        previous_version_id=current.version_id,
    )
