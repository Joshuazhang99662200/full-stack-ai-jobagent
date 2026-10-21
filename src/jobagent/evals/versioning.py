"""Fingerprint the files that steer drafting, so outcomes can be read per version."""

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from jobagent.schemas.evals import HarnessFile, HarnessVersion

# The rules a host follows when it drafts greetings and replies and patrols the
# boards, relative to the skill root. Board manifests are added by directory.
STEERING_REFERENCES = (
    "references/message-generation.md",
    "references/conversation.md",
    "references/patrol.md",
)
STEERING_DIRECTORIES = ("sources",)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def steering_files(skill_root: Path) -> list[Path]:
    """The steering files this skill tree has, in a stable order."""
    paths = [skill_root / name for name in STEERING_REFERENCES]
    for directory in STEERING_DIRECTORIES:
        paths.extend((skill_root / directory).glob("*.yaml"))
    present = [path for path in paths if path.is_file()]
    return sorted(present, key=lambda path: path.relative_to(skill_root).as_posix())


def harness_version(contents: Mapping[str, bytes], *, recorded_at: datetime) -> HarnessVersion:
    """One version for one set of file contents, whatever order they come in."""
    files = [
        HarnessFile(path=path, digest=_sha256(content))
        for path, content in sorted(contents.items())
    ]
    digest = _sha256("\n".join(f"{f.path}\0{f.digest}" for f in files).encode("utf-8"))
    return HarnessVersion(
        version_id=f"HVER_{digest.removeprefix('sha256:')[:16].upper()}",
        digest=digest,
        files=files,
        recorded_at=recorded_at,
    )


def read_harness_version(
    skill_root: Path, *, recorded_at: datetime, extra: Sequence[Path] = ()
) -> HarnessVersion:
    """The version in force now: the skill tree's steering files plus any named extras.

    Extras (such as the person's filter context) are named by file name only; their
    content contributes a digest and is never stored.
    """
    contents = {
        path.relative_to(skill_root).as_posix(): path.read_bytes()
        for path in steering_files(skill_root)
    }
    for path in extra:
        contents[f"extra/{path.name}"] = path.read_bytes()
    return harness_version(contents, recorded_at=recorded_at)
