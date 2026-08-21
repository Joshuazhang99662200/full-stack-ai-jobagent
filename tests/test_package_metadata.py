from pathlib import Path

import jobagent

ROOT = Path(__file__).parents[1]


def test_package_has_version() -> None:
    assert jobagent.__version__ == "0.1.0"


def test_private_paths_are_ignored() -> None:
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in (
        ".env",
        "candidate/private/",
        "*.sqlite3",
        ".jobagent/cache/",
        ".jobagent/browser-profiles/",
    ):
        assert required in rules
