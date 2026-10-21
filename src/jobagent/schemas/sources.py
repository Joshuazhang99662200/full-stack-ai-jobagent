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
the boundary visible instead of leaving a silent hole. Any kind, gated included,
may also declare `host_browser`: how a host agent reads the board in the person's
own signed-in browser. That is a host capability, not a repository route.
"""

from enum import StrEnum
from typing import Annotated, Literal

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


class RecruiterCardSpec(ContractModel):
    """Where one board renders the recruiter for *this* posting.

    Optional on purpose: a board that publishes no recruiter simply omits it and
    the fetcher yields no `RecruiterInfo`, rather than guessing one.
    """

    # Bounded on purpose: recommended-job rails render the same markup, so an
    # unbounded search would attribute another posting's recruiter to this one.
    block_marker: NonEmptyString
    block_limit: int = Field(default=2000, ge=1)
    # The card ends here; anything past it belongs to neighbouring widgets.
    stop_tokens: list[NonEmptyString] = Field(default_factory=list)
    # Presence badges and the like, which are not part of an identity.
    noise_tokens: list[NonEmptyString] = Field(default_factory=list)


class PublicPageSpec(ContractModel):
    """Where one board's JD starts and stops inside a rendered page."""

    start_headings: list[NonEmptyString] = Field(min_length=1)
    stop_headings: list[NonEmptyString] = Field(default_factory=list)
    # Wording the board uses when it withholds the posting. Never save a partial JD.
    gate_markers: list[NonEmptyString] = Field(default_factory=list)
    min_length: int = Field(default=30, ge=1)
    recruiter_card: RecruiterCardSpec | None = None



class HostBrowserSpec(ContractModel):
    """How a host agent may read this board in the person's own browser session.

    This is not an automated route: the repository never drives a browser. The host
    searches and reads at human pace, in a session the person signed into, and hands
    captured postings to `jobs import-observations`, which checks them against this
    spec. Searching never contacts anyone; reaching out is a separate, approved act.
    """

    # Must contain `{query}`; may contain `{city}`, filled from `city_codes`.
    search_url: NonEmptyString
    city_codes: dict[str, NonEmptyString] = Field(default_factory=dict)
    # A captured posting must come from one of these pages, or its provenance is false.
    detail_url_prefixes: list[NonEmptyString] = Field(min_length=1)
    # URL fragments or page wording meaning the board wants a person (verification,
    # risk control). Seeing one ends this board for the session; it is never retried.
    stop_markers: list[NonEmptyString] = Field(min_length=1)
    max_pages_per_session: int = Field(default=3, ge=1, le=10)
    min_seconds_between_pages: int = Field(default=15, ge=5)
    # Detail pages a host may open in one board-day. A ceiling, never raised past 50.
    max_detail_reads_per_day: int = Field(default=50, ge=1, le=50)
    # Where the JD starts on the detail page, as a reading hint for the host.
    jd_headings: list[NonEmptyString] = Field(default_factory=list)
    # How the board renders things today, learned by reading it. Hints for the
    # host only: no repository code depends on them.
    detail_link_pattern: NonEmptyString | None = None
    jd_selector: NonEmptyString | None = None
    reading_hints: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_query_placeholder(self) -> "HostBrowserSpec":
        if "{query}" not in self.search_url:
            raise ValueError("search_url must contain the {query} placeholder")
        return self


class ObservabilitySpec(ContractModel):
    """What a board shows about our own messages, learned by reading it.

    The message list prefixes our latest message with a status word. Only words
    actually seen on the board are declared; a board with no read marker has no
    observable read receipt, and its read rate is reported as unobservable.
    """

    read_markers: list[NonEmptyString] = Field(default_factory=list)
    # Seen while the message is delivered but not yet read (e.g. "[送达]", "[未读]").
    delivered_markers: list[NonEmptyString] = Field(default_factory=list)
    # Whether the board's "who viewed me" list can be read; None until measured.
    profile_views: bool | None = None

    @model_validator(mode="after")
    def require_distinct_markers(self) -> "ObservabilitySpec":
        if set(self.read_markers) & set(self.delivered_markers):
            raise ValueError("a marker cannot mean both delivered and read")
        return self


class ProfileSectionSpec(ContractModel):
    """One editable section of the person's online profile on this board.

    `name` is the field name profile snapshots use. Sections repeated per entry
    (work, projects) are snapshotted as `<name>#<n>`, counting from the top.
    """

    name: NonEmptyString
    label: NonEmptyString
    max_chars: int | None = Field(default=None, ge=1)
    # "shown": the board prints the limit; "inferred": worked out from a counter
    # such as "还可输入 N 个字". A limit must say which it is.
    limit_source: Literal["shown", "inferred"] | None = None
    per_entry: bool = False

    @model_validator(mode="after")
    def require_a_source_for_a_limit(self) -> "ProfileSectionSpec":
        if (self.max_chars is None) != (self.limit_source is None):
            raise ValueError("a limit and where it came from go together")
        return self


class ProfileSpec(ContractModel):
    """Where the online profile lives on this board and how it is divided, as measured.

    Reading hints for the host. Nothing here lets the repository write a profile.
    """

    edit_path: NonEmptyString
    sections: list[ProfileSectionSpec] = Field(min_length=1)
    viewers_path: NonEmptyString | None = None
    reading_hints: list[NonEmptyString] = Field(default_factory=list)


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
    # The currency this board quotes when it prints a bare amount such as `40-60k`.
    # Left unset, such amounts stay unparsed rather than being assigned a guess.
    default_currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    listing: CliListingSpec | None = None
    detail: PublicPageSpec | None = None
    gate: GateSpec | None = None
    host_browser: HostBrowserSpec | None = None
    observability: ObservabilitySpec | None = None
    profile: ProfileSpec | None = None

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
