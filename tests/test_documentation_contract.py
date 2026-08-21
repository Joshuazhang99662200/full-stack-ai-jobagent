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
