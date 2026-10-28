from datetime import timedelta
from pathlib import Path

import pytest

from jobagent.errors import ContractValidationError
from tests.jobs.test_jd_knowledge import NOW, capture, lexicon


def features(number=1, **changes):
    from jobagent.jobs.jd_features import extract_features
    from jobagent.jobs.jd_snapshot import make_snapshot

    data = {
        "observation_id": f"OBS_{number}",
        "job_id": f"JOB_DEMO_{number}",
        "company": f"合成公司{number}",
    }
    data.update(changes)
    return extract_features(make_snapshot(capture(**data), 1), lexicon())


def learning(*events):
    from jobagent.schemas.search_learning import SearchLearningRequest

    return SearchLearningRequest.model_validate(
        {
            "candidate_id": "CAND_DEMO",
            "baseline_queries": ["产品经理"],
            "signals": events,
        }
    )


def signal(number, preference="like", reason=None):
    query = "示例行业 产品经理"
    return {
        "event_id": f"SIG_{number}",
        "candidate_id": "CAND_DEMO",
        "kind": "feedback",
        "job_preference": preference,
        "occurred_at": NOW.isoformat(),
        "owner_text": "岗位方向合适" if preference == "like" else "明确不喜欢这个查询的方向",
        "query_term": query,
        "rejection_reason": reason,
        "features": {"RAG": "RAG"},
        "rejected_features": [],
        "job": {
            "source": "boss",
            "source_job_id": str(number),
            "title": "合成产品",
            "company": f"公司{number}",
            "location": "上海",
            "jd_raw": "负责 RAG 与合成产品交付。",
            "url": f"https://example.com/synthetic/{number}",
            "search_term": query,
            "collected_at": NOW.isoformat(),
        },
    }


def request(**changes):
    from jobagent.schemas.lexicon import CombinationRequest

    data = {
        "candidate_id": "CAND_DEMO",
        "source": "boss",
        "now": NOW,
        "baseline_queries": ["产品经理"],
        "learning": learning().model_dump(mode="json"),
    }
    data.update(changes)
    return CombinationRequest.model_validate(data)


def test_markdown_roundtrip_and_manual_weight_edit_are_authoritative():
    from jobagent.jobs.lexicon import parse_lexicon, serialize_lexicon

    text = serialize_lexicon(lexicon())
    assert parse_lexicon(text) == lexicon()
    modified = text.replace("weight: 1.0", "weight: 2.0")
    assert parse_lexicon(modified).terms[0].weight == 2


def test_empty_template_parses_but_examples_are_not_active_seeds():
    from jobagent.jobs.lexicon import parse_lexicon

    root = Path(__file__).parents[2]
    value = parse_lexicon(
        (root / "skills/job-hunting/references/lexicon-template.md").read_text(
            encoding="utf-8",
        )
    )
    assert value.terms == []


def test_missing_version_or_required_term_fields_are_rejected():
    from jobagent.jobs.lexicon import parse_lexicon, serialize_lexicon

    with pytest.raises(ContractValidationError):
        parse_lexicon("No version or YAML header")
    with pytest.raises(ContractValidationError):
        parse_lexicon(serialize_lexicon(lexicon()).replace("count: 0 | ", ""))


def test_rebuild_counts_unique_jobs_not_repeated_snapshots_or_feedback_approvals():
    from jobagent.jobs.search_learning import rebuild_lexicon

    one, two = features(), features(2)
    result = rebuild_lexicon(lexicon(), [one, two, one], learning(signal(1), signal(2)))
    rag = next(t for t in result.lexicon.terms if t.term == "RAG")
    assert rag.count == 2 and rag.preference_weight > 0
    assert result.lexicon.lexicon_version == "v2"
    replay = rebuild_lexicon(result.lexicon, [two, one], learning(signal(2), signal(1)))
    assert replay.lexicon == result.lexicon and not replay.changed


def test_message_only_feedback_does_not_change_lexicon_version_or_weights():
    from jobagent.jobs.search_learning import rebuild_lexicon

    first = rebuild_lexicon(lexicon(), [features()], learning())
    msg = signal(1)
    msg.update(
        {
            "job_preference": None,
            "message_feedback": "revise",
            "query_term": None,
            "rejection_reason": None,
        }
    )
    result = rebuild_lexicon(first.lexicon, [features()], learning(msg))
    assert result.lexicon == first.lexicon and not result.changed


def test_observation_alone_does_not_create_preference_weight():
    from jobagent.jobs.search_learning import rebuild_lexicon

    result = rebuild_lexicon(lexicon(), [features(), features(2)], learning())
    assert all(term.preference_weight == 0 for term in result.lexicon.terms)


def test_new_terms_remain_candidates_until_independent_repetition():
    from jobagent.jobs.search_learning import rebuild_lexicon
    from jobagent.schemas.lexicon import JDFeature

    first = features(jd_text="新场景用于合成产品交付。")
    first = first.model_copy(
        update={
            "features": [
                JDFeature(dimension="scenario", term="新场景", evidence="新场景", start=0, end=3),
            ]
        }
    )
    observed = rebuild_lexicon(lexicon(), [first], learning()).lexicon
    term = next(t for t in observed.terms if t.term == "新场景")
    assert term.count == 1 and not term.seed and term.preference_weight == 0


def test_combination_generation_is_deterministic_bounded_and_has_source_reasons():
    from jobagent.jobs.query_derivation import SearchQueryDeriver

    deriver = SearchQueryDeriver()
    plan = deriver.derive_combinations(lexicon(), request())
    assert plan == deriver.derive_combinations(lexicon(), request())
    assert 1 <= len(plan.ordered_queries) <= 3
    assert all(2 <= len(q.combination) <= 4 and q.reason for q in plan.ordered_queries)
    assert all(
        "negative" not in q.combination and "hard" not in q.combination
        for q in plan.ordered_queries
    )
    assert plan.grants_delivery_permission is False


def test_recent_query_is_cooled_but_retained_for_future_revisit():
    from jobagent.jobs.query_derivation import SearchQueryDeriver

    deriver = SearchQueryDeriver()
    first = deriver.derive_combinations(lexicon(), request())
    terms = [q.query for q in first.ordered_queries]
    history = [
        {
            "source": "boss",
            "search_term": term,
            "searched_at": NOW.isoformat(),
            "results": 10,
            "new": 1,
        }
        for term in terms
    ]
    second = deriver.derive_combinations(
        lexicon(),
        request(
            now=NOW + timedelta(hours=1),
            history=history,
        ),
    )
    assert not set(terms) & {q.query for q in second.ordered_queries}
    assert set(terms) <= {q.query for q in second.deferred_queries}
    later = deriver.derive_combinations(
        lexicon(),
        request(
            now=NOW + timedelta(days=2),
            history=history,
        ),
    )
    assert set(terms) & {q.query for q in later.ordered_queries}


def test_three_independent_direction_rejections_demote_but_do_not_delete_query():
    from jobagent.jobs.query_derivation import SearchQueryDeriver

    deriver = SearchQueryDeriver()
    events = [signal(i, "dislike", "direction") for i in range(1, 4)]
    plan = deriver.derive_combinations(
        lexicon(),
        request(
            learning=learning(*events).model_dump(mode="json"),
        ),
    )
    queries = plan.ordered_queries + plan.deferred_queries
    rejected = next(q for q in queries if q.query == "示例行业 产品经理")
    assert rejected.demoted and len(rejected.feedback_event_ids) == 3
    salary = [signal(i, "dislike", "salary") for i in range(1, 4)]
    plan = deriver.derive_combinations(
        lexicon(),
        request(
            learning=learning(*salary).model_dump(mode="json"),
        ),
    )
    assert not any(q.demoted for q in plan.ordered_queries + plan.deferred_queries)


def test_two_negatives_or_same_company_do_not_trigger_query_demotion():
    from jobagent.jobs.query_derivation import SearchQueryDeriver

    events = [signal(i, "dislike", "direction") for i in range(1, 4)]
    for event in events:
        event["job"]["company"] = "同一合成公司"
    plan = SearchQueryDeriver().derive_combinations(
        lexicon(),
        request(
            learning=learning(*events).model_dump(mode="json"),
        ),
    )
    assert not any(q.demoted for q in plan.ordered_queries + plan.deferred_queries)


def test_query_attribution_cannot_be_invented_from_an_unrelated_search():
    event = signal(1)
    event["query_term"] = "伪造查询"
    with pytest.raises(ValueError):
        learning(event)


def test_empty_lexicon_falls_back_to_explicit_baseline_without_invented_domain():
    from jobagent.jobs.query_derivation import SearchQueryDeriver

    empty = lexicon().model_copy(update={"terms": []})
    plan = SearchQueryDeriver().derive_combinations(empty, request())
    assert plan.status == "needs_seed" and plan.ordered_queries == []
    assert plan.fallback_queries == ["产品经理"]


def test_design_domain_uses_the_same_engine_without_finance_constants():
    from jobagent.jobs.query_derivation import SearchQueryDeriver
    from jobagent.schemas.lexicon import LexiconTerm

    terms = [
        LexiconTerm(
            dimension=dim,
            term=word,
            source="人工",
            seed=True,
            author="synthetic-designer",
            round_id="INIT",
        )
        for dim, word in [("domain", "品牌"), ("role", "设计师"), ("tech", "Figma")]
    ]
    design = lexicon().model_copy(update={"domain": "合成设计域", "terms": terms})
    plan = SearchQueryDeriver().derive_combinations(design, request())
    assert any(q.query == "品牌 设计师" for q in plan.ordered_queries)
