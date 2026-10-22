import json
from pathlib import Path

from tests.cli.test_outreach import invoke


def context(tmp_path: Path) -> Path:
    path = tmp_path / "filter_context.json"
    path.write_text(
        json.dumps(
            {"preferred_search_terms": ["Agent产品经理", "大模型产品经理", "金融AI产品经理"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_logged_searches_steer_the_next_plan_per_board(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    ctx = ("--filter-context", str(context(tmp_path)))

    code, first = invoke("jobs", "search-plan", *ctx, "--per-site", "1", "--site", "boss", *db)
    assert code == 0 and isinstance(first, dict)
    assert [t["term"] for t in first["boss"]["chosen"]] == ["Agent产品经理"]

    code, logged = invoke(
        "jobs", "search-log", "boss", "Agent产品经理", "--results", "0", "--new", "0", *db
    )
    assert code == 0 and isinstance(logged, dict) and logged["results"] == 0

    code, second = invoke(
        "jobs", "search-plan", *ctx, "--per-site", "1", "--site", "boss", "--site", "liepin", *db
    )
    assert isinstance(second, dict)
    assert [t["term"] for t in second["boss"]["chosen"]] == ["大模型产品经理"]
    # A search on Boss does not use up the term on Liepin.
    assert [t["term"] for t in second["liepin"]["chosen"]] == ["Agent产品经理"]
    boss_stats = {t["term"]: t for t in second["boss"]["stats"]}
    assert boss_stats["Agent产品经理"]["searches"] == 1


def test_a_plan_without_terms_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")

    code, report = invoke(
        "jobs", "search-plan", "--filter-context", str(empty),
        "--database", str(tmp_path / "jobagent.sqlite3"),
    )

    assert code != 0 and isinstance(report, dict) and "error" in report
