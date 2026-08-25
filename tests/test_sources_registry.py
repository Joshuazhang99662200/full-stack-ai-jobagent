"""A third party must be able to add a board without editing this package."""

from pathlib import Path

import pytest
import yaml

from jobagent.connectors.factory import build_detail_fetcher, build_listing_source
from jobagent.errors import ContractValidationError
from jobagent.schemas.sources import SourceKind
from jobagent.sources import SourceRegistry, load_manifest

CUSTOM = {
    "schema_version": "1.0",
    "id": "acme-board",
    "display_name": "Acme Board",
    "kind": "public_page",
    "onboarding_tier": 4,
    "detail": {
        "start_headings": ["Job description"],
        "stop_headings": ["About the company"],
    },
}


def write(directory: Path, name: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_builtin_sources_load_and_declare_their_kind() -> None:
    registry = SourceRegistry.default()
    kinds = {manifest.id: manifest.kind for manifest in registry.all()}

    assert kinds["liepin"] is SourceKind.LISTING_CLI
    assert kinds["zhaopin"] is SourceKind.PUBLIC_PAGE
    assert kinds["boss"] is SourceKind.GATED
    assert kinds["mock"] is SourceKind.FIXTURE


def test_a_user_directory_adds_a_source_without_touching_the_package(tmp_path: Path) -> None:
    write(tmp_path, "acme", CUSTOM)

    registry = SourceRegistry.default(tmp_path)

    assert "acme-board" in registry.ids()
    fetcher = build_detail_fetcher(registry.get("acme-board"))
    assert hasattr(fetcher, "fetch")


def test_user_manifest_cannot_collide_with_a_builtin_id(tmp_path: Path) -> None:
    write(tmp_path, "clash", {**CUSTOM, "id": "liepin"})

    with pytest.raises(ContractValidationError, match="same id"):
        SourceRegistry.default(tmp_path)


def test_gated_manifest_may_not_declare_an_automated_route(tmp_path: Path) -> None:
    """A manifest must not be able to turn a gate into a scrape."""
    payload = {
        "schema_version": "1.0",
        "id": "walled",
        "display_name": "Walled",
        "kind": "gated",
        "gate": {"gate": "waf", "detail": "d", "manual_route": "m"},
        "detail": {"start_headings": ["JD"]},
    }
    path = write(tmp_path, "walled", payload)

    with pytest.raises(ContractValidationError, match="did not satisfy"):
        load_manifest(path)


def test_kind_must_bring_the_section_it_implies(tmp_path: Path) -> None:
    path = write(tmp_path, "empty", {**CUSTOM, "detail": None})

    with pytest.raises(ContractValidationError, match="did not satisfy"):
        load_manifest(path)


def test_cli_listing_manifest_must_map_the_identifying_fields(tmp_path: Path) -> None:
    """A partial field map would silently produce listings missing their identity."""
    payload = {
        "schema_version": "1.0",
        "id": "partial",
        "display_name": "Partial",
        "kind": "listing_cli",
        "listing": {"command": ["tool"], "field_map": {"title": ["t"]}},
    }
    path = write(tmp_path, "partial", payload)

    with pytest.raises(ContractValidationError, match="did not satisfy"):
        load_manifest(path)


def test_malformed_yaml_is_reported_without_dumping_the_file(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "broken.yaml"
    path.write_text("kind: [unclosed", encoding="utf-8")

    with pytest.raises(ContractValidationError) as caught:
        load_manifest(path)

    assert caught.value.details == {"path": "broken.yaml"}


def test_unknown_source_lists_what_is_available() -> None:
    registry = SourceRegistry.default()

    with pytest.raises(ContractValidationError) as caught:
        registry.get("does-not-exist")

    assert "liepin" in caught.value.details["known"]


def test_a_gated_source_offers_no_listing_route_only_a_typed_pause() -> None:
    registry = SourceRegistry.default()
    built = build_listing_source(registry.get("boss"))

    assert not hasattr(built, "search_listings")
    assert hasattr(built, "gate_error")


def test_no_manifest_can_express_delivery() -> None:
    """The manifest contract has no field that could authorize an application."""
    from jobagent.schemas.sources import SourceManifest

    fields = set(SourceManifest.model_fields)
    for forbidden in ("apply", "submit", "deliver", "send", "credentials", "cookie"):
        assert forbidden not in fields
