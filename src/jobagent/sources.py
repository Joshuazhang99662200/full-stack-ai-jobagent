"""Discover declarative source manifests.

Built-in manifests ship beside the skill. A user adds a board by dropping another
YAML file in the same shape into their own directory and pointing `--sources-dir`
at it — no fork, no edit to this package.

User manifests are data. A manifest can describe how to read a board; it cannot
grant authority the workflow does not already have, and it has no way to express
delivery, approval, credential handling or gate circumvention.
"""

from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.schemas.sources import SourceManifest
from jobagent.skill_resources import default_skill_root

BUILTIN_SOURCES_DIR = "sources"


def builtin_sources_dir() -> Path:
    return default_skill_root() / BUILTIN_SOURCES_DIR


def load_manifest(path: Path) -> SourceManifest:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractValidationError(
            "A source manifest could not be read.",
            details={"path": path.name},
        ) from error
    if not isinstance(payload, dict):
        raise ContractValidationError(
            "A source manifest must be a mapping.",
            details={"path": path.name},
        )
    try:
        return SourceManifest.model_validate(payload)
    except ValidationError as error:
        raise ContractValidationError(
            "A source manifest did not satisfy the source contract.",
            details={"path": path.name, "errors": error.error_count()},
        ) from error


class SourceRegistry:
    """The set of sources available to this run, keyed by manifest id."""

    def __init__(self, manifests: Iterable[SourceManifest]) -> None:
        by_id: dict[str, SourceManifest] = {}
        for manifest in manifests:
            if manifest.id in by_id:
                raise ContractValidationError(
                    "Two source manifests declare the same id.",
                    details={"source": manifest.id},
                )
            by_id[manifest.id] = manifest
        self._by_id = by_id

    @classmethod
    def from_directories(cls, *directories: Path | None) -> "SourceRegistry":
        manifests: list[SourceManifest] = []
        for directory in directories:
            if directory is None or not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.yaml")):
                manifests.append(load_manifest(path))
        return cls(manifests)

    @classmethod
    def default(cls, extra_dir: Path | None = None) -> "SourceRegistry":
        return cls.from_directories(builtin_sources_dir(), extra_dir)

    def get(self, source_id: str) -> SourceManifest:
        manifest = self._by_id.get(source_id)
        if manifest is None:
            raise ContractValidationError(
                "Unknown job source.",
                details={"source": source_id, "known": self.ids()},
            )
        return manifest

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def all(self) -> list[SourceManifest]:
        return [self._by_id[key] for key in self.ids()]
