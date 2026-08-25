"""Build connectors from declarative manifests.

This is the only place that maps a source kind to an implementation, so adding a
board never means editing dispatch logic scattered through the CLI.
"""

from pathlib import Path

from jobagent.connectors.cli_source import CliListingSource
from jobagent.connectors.extraction import ExtractionRules
from jobagent.connectors.gated import GatedJobSource
from jobagent.connectors.mock import MockJobSource
from jobagent.connectors.public_pages import PublicPageJobDetailFetcher
from jobagent.errors import ContractValidationError
from jobagent.jobs.ports import JobDetailFetcher
from jobagent.schemas.sources import SourceKind, SourceManifest


def extraction_rules(manifest: SourceManifest) -> ExtractionRules:
    if manifest.detail is None:
        raise ContractValidationError(
            "This source declares no public-page detail route.",
            details={"source": manifest.id},
        )
    spec = manifest.detail
    return ExtractionRules(
        source=manifest.id,
        start_headings=tuple(spec.start_headings),
        stop_headings=tuple(spec.stop_headings),
        **({"gate_markers": tuple(spec.gate_markers)} if spec.gate_markers else {}),
        min_length=spec.min_length,
    )


def build_listing_source(manifest: SourceManifest, *, fixture: Path | None = None) -> object:
    """Return whatever can list jobs for this source, or explain why nothing can."""
    if manifest.kind is SourceKind.LISTING_CLI:
        return CliListingSource(manifest)
    if manifest.kind is SourceKind.FIXTURE:
        if fixture is None:
            raise ContractValidationError(
                "A fixture source needs a fixture path.",
                details={"source": manifest.id},
            )
        return MockJobSource.from_path(fixture)
    if manifest.kind is SourceKind.GATED:
        return GatedJobSource(manifest)
    raise ContractValidationError(
        "This source publishes no listing route; supply a job URL instead.",
        details={"source": manifest.id, "kind": manifest.kind.value},
    )


def build_detail_fetcher(
    manifest: SourceManifest, *, opener: object | None = None
) -> JobDetailFetcher:
    """Return whatever can fetch a full JD, or explain why nothing can."""
    if manifest.kind is SourceKind.PUBLIC_PAGE:
        return PublicPageJobDetailFetcher(manifest, opener=opener)
    if manifest.kind is SourceKind.LISTING_CLI and manifest.detail is not None:
        return PublicPageJobDetailFetcher(manifest, opener=opener)
    if manifest.kind is SourceKind.GATED:
        return GatedJobSource(manifest)
    raise ContractValidationError(
        "This source declares no job-description route.",
        details={"source": manifest.id, "kind": manifest.kind.value},
    )
