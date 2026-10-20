from datetime import date

from jobagent.jobs.query_derivation import SearchQueryDeriver
from jobagent.schemas.candidate import (
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
    Skill,
)
from jobagent.schemas.common import SourceReference, SourceType, TimeRange


def evidence(evidence_id: str, *, confirmed: bool) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.EXPERIENCE,
        statement=f"Statement for {evidence_id}.",
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001#p1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
    )


def profile_with(**overrides: object) -> CandidateProfile:
    defaults: dict[str, object] = {
        "id": "CAND_001",
        "headline": "AI Agent Product Lead · CFA · fintech",
        "experiences": [
            Experience(
                id="EXP_NEW",
                company="NewCo",
                title="Product Lead",
                time_range=TimeRange(start=date(2025, 8, 1)),
                evidence_ids=["EVID_A", "EVID_B"],
            ),
            Experience(
                id="EXP_OLD",
                company="OldCo",
                title="Analyst",
                time_range=TimeRange(start=date(2021, 7, 1), end=date(2022, 8, 31)),
                evidence_ids=["EVID_C"],
            ),
        ],
        "skills": [Skill(name="Multi-agent orchestration", evidence_ids=["EVID_A"])],
    }
    defaults.update(overrides)
    return CandidateProfile(**defaults)  # type: ignore[arg-type]


def test_terms_are_ranked_by_origin_then_support() -> None:
    confirmed = [evidence(item, confirmed=True) for item in ("EVID_A", "EVID_B", "EVID_C")]

    result = SearchQueryDeriver().derive(profile_with(), confirmed)

    assert [item.term for item in result.suggestions] == [
        "AI Agent Product Lead",
        "Product Lead",
        "Analyst",
        "Multi-agent orchestration",
    ]
    assert [item.origin.value for item in result.suggestions] == [
        "headline",
        "recent_title",
        "recent_title",
        "skill",
    ]
    assert result.suggestions[1].support_count == 2
    assert result.suggestions[1].supporting_evidence_ids == ["EVID_A", "EVID_B"]
    assert result.skipped_unconfirmed_evidence_count == 0


def test_headline_keeps_only_its_leading_segment() -> None:
    result = SearchQueryDeriver().derive(profile_with(), [evidence("EVID_A", confirmed=True)])
    assert result.suggestions[0].term == "AI Agent Product Lead"


def test_unconfirmed_evidence_cannot_support_a_term() -> None:
    unconfirmed = [evidence(item, confirmed=False) for item in ("EVID_A", "EVID_B", "EVID_C")]

    result = SearchQueryDeriver().derive(profile_with(), unconfirmed)

    # Only the headline survives; every evidence-linked term lost its support.
    assert [item.term for item in result.suggestions] == ["AI Agent Product Lead"]
    assert result.skipped_unconfirmed_evidence_count == 3


def test_location_is_threaded_into_every_query() -> None:
    result = SearchQueryDeriver().derive(
        profile_with(), [evidence("EVID_A", confirmed=True)], location="Shanghai"
    )
    assert {item.query.location for item in result.suggestions} == {"Shanghai"}
    assert all(item.query.query == item.term for item in result.suggestions)


def test_duplicate_terms_are_emitted_once() -> None:
    duplicated = profile_with(
        skills=[
            Skill(name="Product Lead", evidence_ids=["EVID_A"]),
            Skill(name="  product lead  ", evidence_ids=["EVID_B"]),
        ]
    )

    result = SearchQueryDeriver().derive(
        duplicated, [evidence(item, confirmed=True) for item in ("EVID_A", "EVID_B")]
    )

    assert [item.term for item in result.suggestions].count("Product Lead") == 1


def test_limit_is_respected() -> None:
    confirmed = [evidence(item, confirmed=True) for item in ("EVID_A", "EVID_B", "EVID_C")]
    result = SearchQueryDeriver(max_suggestions=2).derive(profile_with(), confirmed)
    assert len(result.suggestions) == 2


def stated(evidence_id: str, statement: str, *, confirmed: bool = True) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.EXPERIENCE,
        statement=statement,
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001#p1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
    )


def test_target_role_drives_compact_terms_backed_by_evidence() -> None:
    items = [
        stated("EVID_A", "编排 13 个 Agent 协同完成尽调。"),
        stated("EVID_B", "把提示词沉淀为模块化 Skill。"),
        stated("EVID_C", "搭建跨厂商大模型评测框架。", confirmed=False),
    ]

    result = SearchQueryDeriver().derive(
        profile_with(), items, target_roles=["AI Agent 产品经理"]
    )

    terms = [item.term for item in result.suggestions]
    assert terms[0] == "AI Agent产品经理"
    assert "Agent产品经理" in terms
    assert "Skill产品经理" in terms
    # Only confirmed evidence may back a modifier.
    assert "大模型产品经理" not in terms
    by_term = {item.term: item for item in result.suggestions}
    assert by_term["Skill产品经理"].supporting_evidence_ids == ["EVID_B"]


def test_target_role_drops_unrelated_past_titles_and_bare_skills() -> None:
    items = [stated(item, "Agent work.") for item in ("EVID_A", "EVID_B", "EVID_C")]

    result = SearchQueryDeriver().derive(
        profile_with(), items, target_roles=["AI Agent 产品经理"]
    )

    terms = [item.term for item in result.suggestions]
    assert "Analyst" not in terms
    assert "Product Lead" not in terms
    assert "Multi-agent orchestration" not in terms


def test_without_target_roles_behaviour_is_unchanged() -> None:
    confirmed = [evidence(item, confirmed=True) for item in ("EVID_A", "EVID_B", "EVID_C")]

    result = SearchQueryDeriver().derive(profile_with(), confirmed, target_roles=[])

    assert [item.term for item in result.suggestions][:3] == [
        "AI Agent Product Lead",
        "Product Lead",
        "Analyst",
    ]
