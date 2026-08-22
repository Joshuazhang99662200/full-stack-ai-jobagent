from pathlib import Path

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
