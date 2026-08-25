"""Declarative job-source manifests.

A source is described by data, not code. Adding a board means dropping one YAML
file next to the built-in ones; the shipped sources are reference implementations
of this contract, not privileged cases.

The four kinds cover what a board can actually offer:

- `fixture`      synthetic records, for offline development
- `listing_cli`  an external CLI is invoked as an opaque subprocess
- `public_page`  the JD is served in public server-rendered HTML
- `gated`        no lawful automated route exists; the workflow pauses for a human

`gated` is a first-class kind on purpose. Modelling an unreachable board keeps
the boundary visible instead of leaving a silent hole.
"""

from enum import StrEnum

from pydantic import Field, model_validator

from jobagent.schemas.common import ContractModel, NonEmptyString

SourceId = NonEmptyString


class SourceKind(StrEnum):
    FIXTURE = "fixture"
    LISTING_CLI = "listing_cli"
    PUBLIC_PAGE = "public_page"
    GATED = "gated"


class CliListingSpec(ContractModel):
    """How to drive an external CLI that returns job listings as JSON."""

    command: list[NonEmptyString] = Field(min_length=1)
    # JobSearchQuery field name -> CLI flag, e.g. {"query": "--job-name"}.
    query_options: dict[str, NonEmptyString] = Field(default_factory=dict)
    # Keys to unwrap when the payload nests its list, tried in order.
    envelope_keys: list[NonEmptyString] = Field(default_factory=list)
    # Listing field -> candidate source keys, tried in order.
    field_map: dict[str, list[NonEmptyString]] = Field(default_factory=dict)
    # Substrings meaning a person must clear a platform state. Never retried.
    intervention_markers: list[NonEmptyString] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def require_identifying_fields(self) -> "CliListingSpec":
        missing = [
            name
            for name in ("source_job_id", "title", "company", "url")
            if not self.field_map.get(name)
        ]
        if missing:
            raise ValueError(f"field_map must map the identifying fields: {missing}")
        return self


class PublicPageSpec(ContractModel):
    """Where one board's JD starts and stops inside a rendered page."""

    start_headings: list[NonEmptyString] = Field(min_length=1)
    stop_headings: list[NonEmptyString] = Field(default_factory=list)
    # Wording the board uses when it withholds the posting. Never save a partial JD.
    gate_markers: list[NonEmptyString] = Field(default_factory=list)
    min_length: int = Field(default=30, ge=1)


class GateSpec(ContractModel):
    """Why a board cannot be reached, and what the person should do instead."""

    gate: NonEmptyString
    detail: NonEmptyString
    manual_route: NonEmptyString


class SourceManifest(ContractModel):
    id: SourceId
    display_name: NonEmptyString
    kind: SourceKind
    # Which onboarding tier this source was admitted at; see source-onboarding.md.
    onboarding_tier: int = Field(default=0, ge=0, le=5)
    notes: str = ""
    listing: CliListingSpec | None = None
    detail: PublicPageSpec | None = None
    gate: GateSpec | None = None

    @model_validator(mode="after")
    def require_the_spec_its_kind_implies(self) -> "SourceManifest":
        required = {
            SourceKind.LISTING_CLI: ("listing", self.listing),
            SourceKind.PUBLIC_PAGE: ("detail", self.detail),
            SourceKind.GATED: ("gate", self.gate),
        }.get(self.kind)
        if required is not None and required[1] is None:
            raise ValueError(f"kind '{self.kind.value}' requires a '{required[0]}' section")
        if self.kind is SourceKind.GATED and (self.listing or self.detail):
            raise ValueError("a gated source must not declare an automated route")
        return self
