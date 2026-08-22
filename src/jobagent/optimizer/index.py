"""Confined loading and deterministic compilation for capability indexes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from jobagent.errors import CapabilityRegistryError
from jobagent.schemas.optimizer_registry import (
    CapabilityIndexDocument,
    CapabilityIndexEntry,
    CapabilityRegistrySnapshot,
)


def _reject_duplicate_mapping_keys(node: Node | None) -> None:
    """Reject literal duplicate keys before safe construction can overwrite them."""
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode):
                identity = (key_node.tag, key_node.value)
                if identity in seen:
                    raise yaml.YAMLError("duplicate mapping key")
                seen.add(identity)
            _reject_duplicate_mapping_keys(key_node)
            _reject_duplicate_mapping_keys(value_node)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _reject_duplicate_mapping_keys(child)


class CapabilityIndexLoader:
    """Load index documents from a single confined filesystem root."""

    def __init__(self, root: Path) -> None:
        try:
            self._root = root.resolve()
        except (OSError, RuntimeError):
            raise CapabilityRegistryError("Capability index root is invalid.") from None

    def load(self, relative_path: Path) -> CapabilityIndexDocument:
        """Parse and validate one YAML document without exposing its contents."""
        if relative_path.is_absolute():
            self._raise_invalid_document(relative_path)

        try:
            resolved = (self._root / relative_path).resolve()
            if not resolved.is_relative_to(self._root):
                self._raise_invalid_document(relative_path)
            body = resolved.read_text(encoding="utf-8")
            _reject_duplicate_mapping_keys(yaml.compose(body, Loader=yaml.SafeLoader))
            payload = yaml.safe_load(body)
            if not isinstance(payload, dict):
                self._raise_invalid_document(relative_path)
            return CapabilityIndexDocument.model_validate(payload)
        except (OSError, RuntimeError, UnicodeError, yaml.YAMLError, ValidationError):
            self._raise_invalid_document(relative_path)

    @staticmethod
    def _raise_invalid_document(
        relative_path: Path,
    ) -> NoReturn:
        error = CapabilityRegistryError(
            "Capability index document is invalid.",
            details={"path": relative_path.as_posix()},
        )
        raise error from None


class CapabilityRegistryCompiler:
    """Combine validated documents into a stable registry snapshot."""

    def __init__(self, loader: CapabilityIndexLoader) -> None:
        self._loader = loader

    def compile(self, paths: Sequence[Path]) -> CapabilityRegistrySnapshot:
        """Sort, cross-check, and digest all entries from the given documents."""
        if not paths:
            raise CapabilityRegistryError(
                "Capability registry requires at least one document."
            )
        entries = sorted(
            (
                entry
                for path in paths
                for entry in self._loader.load(path).entries
            ),
            key=lambda entry: entry.id,
        )
        self._validate_unique_ids(entries)
        self._validate_references(entries)

        canonical = json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        return CapabilityRegistrySnapshot(entries=tuple(entries), digest=digest)

    @staticmethod
    def _validate_unique_ids(entries: Sequence[CapabilityIndexEntry]) -> None:
        previous_id: str | None = None
        for entry in entries:
            if entry.id == previous_id:
                raise CapabilityRegistryError(
                    "Capability registry contains duplicate capability id.",
                    details={"capability_id": entry.id},
                )
            previous_id = entry.id

    @staticmethod
    def _validate_references(entries: Sequence[CapabilityIndexEntry]) -> None:
        known_ids = {entry.id for entry in entries}
        for entry in entries:
            unknown_ids = sorted(
                (set(entry.dependencies) | set(entry.verifiers)) - known_ids
            )
            if unknown_ids:
                raise CapabilityRegistryError(
                    "Capability registry contains unknown registry reference.",
                    details={
                        "capability_id": entry.id,
                        "reference_id": unknown_ids[0],
                    },
                )
