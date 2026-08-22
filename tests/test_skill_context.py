from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "job-hunting"


def test_skill_entrypoint_routes_every_sensitive_mode() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for reference in (
        "references/evidence-policy.md",
        "references/hitl-approval.md",
        "optimizer/SKILL.md",
        "references/connector-contract.md",
        "references/oss/source-manifest.yaml",
    ):
        assert reference in text


def test_reference_only_source_is_explicit() -> None:
    text = (SKILL / "references/oss/source-manifest.yaml").read_text(encoding="utf-8")
    assert "Auto-JobHunter" in text
    assert "reference-only" in text
    assert "non-commercial" in text


def test_product_skill_routes_deep_optimizer_work_to_nested_skill() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "optimizer/SKILL.md" in text


def test_nested_optimizer_skill_declares_progressive_loading_and_boundaries() -> None:
    text = (SKILL / "optimizer/SKILL.md").read_text(encoding="utf-8")
    for required in (
        "L0",
        "L1",
        "L2",
        "L3",
        "canonical Evidence",
        "explicit user confirmation",
    ):
        assert required in text
    for forbidden in ("send application", "bypass captcha", "perform login"):
        assert forbidden not in text.casefold()
