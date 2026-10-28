# ruff: noqa: RUF001 -- Preserve Chinese source punctuation.
from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError

NOW = datetime(2026, 10, 28, 2, tzinfo=UTC)


def capture(**changes):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput

    data = {
        "observation_id": "OBS_1",
        "job_id": "JOB_DEMO_1",
        "platform": "boss",
        "job_url": "https://www.zhipin.com/job_detail/synthetic-1.html",
        "fetched_at": NOW,
        "query_hit": "示例 产品经理",
        "discovery_kind": "search",
        "title": "合成产品岗位",
        "company": "合成公司",
        "location": "上海",
        "salary_raw": "15-25K",
        "jd_text": "负责示例行业的产品经理工作。使用 Python 和 RAG 构建合成业务。",
        "completeness": "full",
    }
    data.update(changes)
    return JDSnapshotInput.model_validate(data)


def lexicon():
    from jobagent.schemas.lexicon import Lexicon

    terms = [
        {
            "dimension": dim,
            "term": term,
            "aliases": aliases,
            "source": "人工",
            "seed": True,
            "author": "synthetic-owner",
            "round_id": "INIT",
        }
        for dim, term, aliases in [
            ("domain", "示例行业", []),
            ("role", "产品经理", []),
            ("tech", "Python", []),
            ("tech", "RAG", ["检索增强"]),
        ]
    ]
    return Lexicon.model_validate(
        {
            "lexicon_version": "v1",
            "domain": "合成测试域",
            "updated_at": "2026-10-28",
            "based_on_snapshots": 0,
            "based_on_feedback_events": 0,
            "terms": terms,
        }
    )


def repo(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

    database = Database(tmp_path / "jd.sqlite3")
    database.migrate()
    return SqliteJDSnapshotRepository(database)


def snapshot(tmp_path, **changes):
    return repo(tmp_path).capture(capture(**changes)).snapshot


def test_same_content_different_queries_preserves_both_discoveries(tmp_path):
    store = repo(tmp_path)
    first = store.capture(capture())
    second = store.capture(
        capture(
            observation_id="OBS_2",
            query_hit="另一查询",
            fetched_at=NOW + timedelta(hours=1),
        )
    )
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert len(store.discoveries("JOB_DEMO_1")) == 2
    assert len(store.list_snapshots("JOB_DEMO_1")) == 1
    assert store.capture(capture()).snapshot == first.snapshot
    with pytest.raises(ContractValidationError):
        store.capture(capture(title="同ID不能改文"))


def test_jd_change_and_return_to_an_old_text_append_versions_without_overwriting(tmp_path):
    store = repo(tmp_path)
    first = store.capture(capture()).snapshot
    second = store.capture(
        capture(
            observation_id="OBS_2",
            jd_text="全新合成职责。负责设计系统与产品交付。",
            fetched_at=NOW + timedelta(hours=1),
        )
    ).snapshot
    third = store.capture(
        capture(
            observation_id="OBS_3",
            fetched_at=NOW + timedelta(hours=2),
        )
    ).snapshot
    assert [s.snapshot_version for s in store.list_snapshots("JOB_DEMO_1")] == [1, 2, 3]
    assert first.jd_text_hash != second.jd_text_hash
    assert first.jd_text_hash == third.jd_text_hash
    assert first.snapshot_id != third.snapshot_id
    with pytest.raises(ContractValidationError):
        store.capture(capture(observation_id="OLD", jd_text="陈旧内容", fetched_at=NOW))


def test_snapshot_hash_uses_exact_raw_whitespace_not_normalized_job_text(tmp_path):
    import hashlib

    text = "原样第一行\n  原样第二行 "
    result = snapshot(tmp_path, jd_text=text)
    assert result.jd_text == text
    assert result.jd_text_hash == "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def test_manual_capture_does_not_invent_a_query(tmp_path):
    result = snapshot(tmp_path, discovery_kind="manual", query_hit=None)
    assert result.query_hit is None
    with pytest.raises(ValueError):
        capture(query_hit=None)


@pytest.mark.parametrize(
    "term",
    [
        "Python",
        "RAG",
        "示例行业",
        "产品经理",
        "检索增强",
        "Python/RAG",
        "Python 产品经理",
        "示例行业 RAG",
        "产品经理 RAG",
        "示例行业 Python",
    ],
)
def test_ten_synthetic_jds_have_exact_span_evidence(tmp_path, term):
    from jobagent.jobs.jd_features import extract_features

    snap = snapshot(tmp_path, jd_text=f"合成岗位职责：{term}。请按公开要求完成合成交付。")
    result = extract_features(snap, lexicon())
    assert result.features
    for feature in result.features:
        assert snap.jd_text[feature.start : feature.end] == feature.evidence


def test_listing_or_partial_snapshot_never_contributes_features(tmp_path):
    from jobagent.jobs.jd_features import extract_features

    for quality in ["listing", "partial"]:
        snap = snapshot(tmp_path, observation_id=quality, completeness=quality)
        assert extract_features(snap, lexicon()).features == []


def test_negation_and_preferred_requirements_are_not_silently_made_required(tmp_path):
    from jobagent.jobs.jd_features import extract_features

    result = extract_features(
        snapshot(tmp_path, jd_text="不要求 Python。RAG 经验优先。"), lexicon()
    )
    python = next(f for f in result.features if f.term == "Python")
    rag = next(f for f in result.features if f.term == "RAG")
    assert python.polarity == "negated"
    assert rag.requirement_level == "preferred"


def test_invalid_model_schema_dimension_evidence_or_alias_falls_back(tmp_path):
    from jobagent.jobs.jd_factorization import factorize
    from jobagent.jobs.jd_features import extract_features

    snap = snapshot(tmp_path)
    baseline = extract_features(snap, lexicon())
    valid = baseline.model_dump(mode="json")
    result = factorize(snap, lexicon(), valid)
    assert result.factorization == "model"
    for changed in [
        {
            **valid,
            "features": [
                {"dimension": "invented", "term": "X", "evidence": "X", "start": 0, "end": 1}
            ],
        },
        {
            **valid,
            "features": [
                {"dimension": "tech", "term": "X", "evidence": "虚构", "start": 0, "end": 2}
            ],
        },
        {
            **valid,
            "features": [
                {
                    "dimension": "tech",
                    "term": "误归一",
                    "evidence": "Python",
                    "start": snap.jd_text.index("Python"),
                    "end": snap.jd_text.index("Python") + 6,
                }
            ],
        },
        {"invalid": "PRIVATE_SENTINEL"},
    ]:
        output = factorize(snap, lexicon(), changed)
        assert output.factorization == "fallback"
        assert output.features == baseline.features
        assert output.issues and "PRIVATE_SENTINEL" not in str(output.issues)
