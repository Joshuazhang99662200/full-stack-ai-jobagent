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


def test_main_boards_declare_a_host_browser_route_with_stop_markers() -> None:
    registry = SourceRegistry.default()

    for source_id in ("boss", "zhaopin", "liepin"):
        spec = registry.get(source_id).host_browser
        assert spec is not None, source_id
        assert "{query}" in spec.search_url
        assert spec.detail_url_prefixes
        assert spec.stop_markers
    # The host route never turns a gated board into a repository-side scrape.
    assert registry.get("boss").kind is SourceKind.GATED


def test_host_browser_search_url_must_take_the_query(tmp_path: Path) -> None:
    payload = {
        **CUSTOM,
        "host_browser": {
            "search_url": "https://acme.example/jobs",
            "detail_url_prefixes": ["https://acme.example/job/"],
            "stop_markers": ["captcha"],
        },
    }
    path = write(tmp_path, "acme", payload)

    with pytest.raises(ContractValidationError, match="did not satisfy"):
        load_manifest(path)


def test_host_browser_spec_cannot_express_contact_or_delivery() -> None:
    from jobagent.schemas.sources import HostBrowserSpec

    fields = set(HostBrowserSpec.model_fields)
    for forbidden in ("apply", "submit", "deliver", "send", "message", "credentials", "cookie"):
        assert not any(forbidden in field for field in fields)


def test_host_routes_carry_reading_hints_and_a_daily_read_cap() -> None:
    registry = SourceRegistry.default()

    for source_id in ("boss", "zhaopin"):
        spec = registry.get(source_id).host_browser
        assert spec is not None
        assert spec.reading_hints, source_id
        assert 1 <= spec.max_detail_reads_per_day <= 50
    boss = registry.get("boss").host_browser
    assert boss is not None and boss.detail_link_pattern == "/job_detail/"


def test_boards_declare_what_they_show_about_our_own_messages() -> None:
    """Read receipts are learned by reading each board, never assumed."""
    registry = SourceRegistry.default()

    boss = registry.get("boss").observability
    liepin = registry.get("liepin").observability
    zhaopin = registry.get("zhaopin").observability

    assert boss is not None and boss.read_markers == ["[已读]"]
    assert boss.delivered_markers == ["[送达]"]
    assert liepin is not None and liepin.read_markers == ["[已读]"]
    assert liepin.delivered_markers == ["[未读]"]
    # Zhaopin has only ever shown "[送达]"; until a read marker is seen, read
    # receipts there stay unobservable rather than assumed.
    assert zhaopin is not None and zhaopin.read_markers == []
    assert zhaopin.delivered_markers == ["[送达]"]
    assert registry.get("mock").observability is None


def test_a_marker_may_not_mean_both_delivered_and_read(tmp_path: Path) -> None:
    payload = {
        **CUSTOM,
        "observability": {"read_markers": ["[已读]"], "delivered_markers": ["[已读]"]},
    }
    with pytest.raises(ContractValidationError):
        load_manifest(write(tmp_path, "acme-board", payload))


def test_boards_declare_their_profile_sections_as_measured() -> None:
    registry = SourceRegistry.default()

    boss = registry.get("boss").profile
    liepin = registry.get("liepin").profile
    zhaopin = registry.get("zhaopin").profile
    assert boss is not None and liepin is not None and zhaopin is not None

    assert {s.name: s.max_chars for s in boss.sections}["advantage"] == 1000
    assert {s.name: s.max_chars for s in liepin.sections}["highlights"] == 1000
    # Zhaopin shows only "还可输入 N 个字", so its limits are inferred, not read.
    advantage = next(s for s in zhaopin.sections if s.name == "advantage")
    assert advantage.limit_source == "inferred"

    observability = {m.id: m.observability for m in registry.all() if m.observability}
    assert observability["liepin"].profile_views is True
    assert observability["zhaopin"].profile_views is True
    assert observability["boss"].profile_views is None  # not yet measured
    assert liepin.viewers_path == "/resume/viewed-log"


def test_a_profile_section_limit_says_where_it_came_from(tmp_path: Path) -> None:
    payload = {
        **CUSTOM,
        "profile": {
            "edit_path": "/resume",
            "sections": [{"name": "advantage", "label": "个人优势", "max_chars": 500}],
        },
    }
    with pytest.raises(ContractValidationError):
        load_manifest(write(tmp_path, "acme-board", payload))
