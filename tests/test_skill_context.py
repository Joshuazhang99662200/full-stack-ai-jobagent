from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "job-hunting"


def test_skill_entrypoint_routes_every_sensitive_mode() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for reference in (
        "references/evidence-policy.md",
        "references/hitl-approval.md",
        "references/optimizer/quality-gates.md",
        "references/connector-contract.md",
        "references/oss/source-manifest.yaml",
    ):
        assert reference in text


def test_reference_only_source_is_explicit() -> None:
    text = (SKILL / "references/oss/source-manifest.yaml").read_text(encoding="utf-8")
    assert "Auto-JobHunter" in text
    assert "reference-only" in text
    assert "non-commercial" in text
