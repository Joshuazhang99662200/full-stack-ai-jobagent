from datetime import UTC, datetime, timedelta

from jobagent.jobs.search_plan import plan_searches
from jobagent.schemas.job_intelligence import JobSearchHit, SearchRun

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
TERMS = ["Agent产品经理", "AI投研产品经理", "大模型产品经理", "金融AI产品经理"]


def run(term: str, hours_ago: float, results: int = 10, new: int = 2) -> SearchRun:
    return SearchRun(
        source="boss",
        search_term=term,
        searched_at=NOW - timedelta(hours=hours_ago),
        results=results,
        new=new,
    )


def hit(job_id: str, term: str) -> JobSearchHit:
    return JobSearchHit(job_id=job_id, source="boss", search_term=term, collected_at=NOW)


def test_terms_never_searched_on_a_site_come_first_in_config_order() -> None:
    plan = plan_searches(
        TERMS, "boss", runs=[run("Agent产品经理", 1)], hits=[], tiers={}, per_site=2
    )

    assert [t.term for t in plan.chosen] == ["AI投研产品经理", "大模型产品经理"]


def test_once_all_were_searched_the_oldest_rotate_back_in() -> None:
    runs = [run(t, h) for t, h in zip(TERMS, [1, 5, 3, 9], strict=True)]

    plan = plan_searches(TERMS, "boss", runs=runs, hits=[], tiers={}, per_site=2)

    assert [t.term for t in plan.chosen] == ["金融AI产品经理", "AI投研产品经理"]


def test_one_slot_goes_to_the_term_that_turned_up_the_most_promising_jobs() -> None:
    runs = [run(t, h) for t, h in zip(TERMS, [1, 5, 3, 9], strict=True)]
    hits = [hit("J1", "Agent产品经理"), hit("J2", "Agent产品经理"), hit("J3", "大模型产品经理")]
    tiers = {"J1": "strong_match", "J2": "possible_match", "J3": "weak_match"}

    plan = plan_searches(TERMS, "boss", runs=runs, hits=hits, tiers=tiers, per_site=3)

    assert [t.term for t in plan.chosen] == ["金融AI产品经理", "AI投研产品经理", "Agent产品经理"]
    best = next(t for t in plan.stats if t.term == "Agent产品经理")
    assert (best.searches, best.hits, best.promising) == (1, 2, 2)


def test_other_sites_runs_do_not_count() -> None:
    other = run("AI投研产品经理", 1).model_copy(update={"source": "liepin"})

    plan = plan_searches(TERMS, "boss", runs=[other], hits=[], tiers={}, per_site=1)

    assert [t.term for t in plan.chosen] == ["Agent产品经理"]
