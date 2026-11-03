import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from jobagent.cli.pipeline import pipeline_app

ROOT = Path(__file__).parents[1]


def test_architecture_documents_invariants() -> None:
    text = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    assert "CandidateProfile != Resume" in text
    assert "Approval != Send" in text
    assert "CAPTCHA != Retry" in text


def test_oss_review_records_all_sources() -> None:
    text = (ROOT / "docs/oss-review.md").read_text(encoding="utf-8")
    for project in ("AgentMesh-JobAgent", "open-boss", "Auto-JobHunter"):
        assert project in text


def test_release_contract_files_exist() -> None:
    """The foundation design requires these before a public release."""
    for name in (
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "PRIVACY.md",
        "AGENTS.md",
        ".env.example",
    ):
        assert (ROOT / name).is_file(), name


def test_env_example_carries_no_values() -> None:
    """The template must never ship a real key."""
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            assert line.endswith("="), line


def test_readme_links_the_release_contract_documents() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in ("CONTRIBUTING.md", "SECURITY.md", "PRIVACY.md", "AGENTS.md"):
        assert target in text


def test_agent_panel_entrypoints_use_one_current_protocol() -> None:
    for name in ("AGENTS.md", "hosts/personal-ai/README.md", "docs/polling-console.md",
                 "frontend/README.md"):
        text = (ROOT / name).read_text(encoding="utf-8-sig")
        assert "muse-panel.md" in text, name


def test_active_documentation_links_resolve() -> None:
    pending = [ROOT / name for name in (
        "README.md", "AGENTS.md", "CONTRIBUTING.md", "docs/README.md",
        "hosts/personal-ai/README.md", "hosts/personal-ai/memory.md",
        "hosts/personal-ai/tasks.md", "skills/job-hunting/SKILL.md", "frontend/README.md",
    )]
    visited = set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        assert source.is_file(), source.relative_to(ROOT)
        visited.add(source)
        text = source.read_text(encoding="utf-8-sig")
        for link in re.findall(r"\]\(([^)\s]+)\)", text):
            if link.startswith("#") or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", link):
                continue
            path = unquote(link.split("#", 1)[0])
            target = (source.parent / path).resolve()
            assert target.is_relative_to(ROOT), (source.relative_to(ROOT), link)
            assert target.exists(), (source.relative_to(ROOT), link)
            historical = any(part in {"superpowers", "reviews"} for part in target.parts)
            if target.suffix == ".md" and not historical:
                pending.append(target)


@pytest.mark.parametrize("name", ["README.md", "docs/usage.md", "hosts/personal-ai/README.md"])
def test_current_onboarding_points_to_the_current_repository(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    current = "Joshuazhang99662200/career-harness"
    previous = "Joshuazhang99662200/" + "full-stack-ai-jobagent"
    assert current in text, name
    assert previous not in text, name
    if "git clone" in text:
        assert f"git clone https://github.com/{current}.git" in text
        assert "cd career-harness" in text


def test_operations_guide_documents_implemented_pipeline_commands() -> None:
    text = (ROOT / "docs/usage.md").read_text(encoding="utf-8")
    operations = {
        "metrics", "diagnose", "metric-show", "diagnosis-show",
        "rule-propose", "rule-confirm", "confirmed-rules", "rule-review",
    }
    registered = {command.name for command in pipeline_app.registered_commands}
    documented = set(re.findall(r"`jobagent pipeline ([a-z-]+)`", text))
    assert operations <= registered
    assert operations <= documented
    assert documented <= registered
    assert "漏斗计算、诊断、实验和其余飞轮编排仍待实现" not in text
