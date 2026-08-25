"""Contracts used as structured model output must have strict-transformable schemas.

An untyped schema node (typically a bare `Any` field) is accepted by Pydantic but
rejected by strict JSON-schema output, and the failure surfaces only at call time.
"""

from typing import Any

import pytest

from jobagent.schemas.candidate import CandidateDraft
from jobagent.schemas.job_intelligence import RequirementMatchSet
from jobagent.schemas.jobs import JobRequirementProfile

REASONING_OUTPUT_TYPES = [CandidateDraft, JobRequirementProfile, RequirementMatchSet]
_TYPE_KEYS = {"type", "anyOf", "oneOf", "allOf", "$ref", "enum", "const"}


def untyped_nodes(schema: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for name, definition in (schema.get("$defs") or {}).items():
        for field, spec in (definition.get("properties") or {}).items():
            if not (_TYPE_KEYS & spec.keys()):
                found.append(f"{name}.{field}")
    for field, spec in (schema.get("properties") or {}).items():
        if not (_TYPE_KEYS & spec.keys()):
            found.append(field)
    return sorted(found)


@pytest.mark.parametrize("output_type", REASONING_OUTPUT_TYPES, ids=lambda t: t.__name__)
def test_reasoning_output_schema_has_no_untyped_field(output_type: type) -> None:
    assert untyped_nodes(output_type.model_json_schema()) == []


@pytest.mark.parametrize("output_type", REASONING_OUTPUT_TYPES, ids=lambda t: t.__name__)
def test_schema_survives_the_sdk_strict_transform(output_type: type) -> None:
    transform_schema = pytest.importorskip("anthropic.lib._parse._transform").transform_schema
    transform_schema(output_type.model_json_schema())
