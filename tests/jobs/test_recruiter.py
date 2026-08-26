import pytest

from jobagent.jobs.recruiter import (
    DEFAULT_ROUTING_THRESHOLD,
    RecruiterClassifier,
    is_routable,
)
from jobagent.schemas.jobs import RecruiterType


def classify(**kwargs: str | None):
    return RecruiterClassifier().classify(**kwargs)  # type: ignore[arg-type]


def test_platform_stated_headhunter_wins_and_is_routable() -> None:
    """Liepin writes 猎头 itself, so this is observed rather than deduced."""
    result = classify(
        name="许先生",
        title="猎头 · 北京优九人才咨询有限公司",
        organization="北京优九人才咨询有限公司",
        hiring_company="某北京基金/证券/期货公司",
    )

    assert result.type is RecruiterType.HEADHUNTER
    assert result.type_confidence == pytest.approx(0.95)
    assert result.type_signals == ["platform_label:猎头"]
    assert is_routable(result)


def test_employer_side_recruiter_is_not_forced_into_hr_or_hiring_manager() -> None:
    """The card proves employer-side but not which role, so it must not guess."""
    result = classify(
        name="孙女士",
        title="宁波银行",
        organization="宁波银行",
        hiring_company="宁波银行",
    )

    assert result.type is RecruiterType.INTERNAL_UNSPECIFIED
    assert result.type_signals == ["organization_matches_hiring_company"]
    assert not is_routable(result), "an unspecified internal recruiter must fall back"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("HRBP", RecruiterType.HR),
        ("人力资源经理", RecruiterType.HR),
        ("招聘专员", RecruiterType.HR),
        ("技术总监", RecruiterType.HIRING_MANAGER),
        ("产品负责人", RecruiterType.HIRING_MANAGER),
        ("CTO", RecruiterType.HIRING_MANAGER),
    ],
)
def test_titles_route_to_their_role(title: str, expected: RecruiterType) -> None:
    result = classify(name="某某", title=title, organization="示例科技", hiring_company="示例科技")
    assert result.type is expected
    assert result.type_confidence >= DEFAULT_ROUTING_THRESHOLD
    assert is_routable(result)


def test_hr_marker_outranks_a_manager_marker_in_the_same_title() -> None:
    result = classify(name="某某", title="人力资源总监", hiring_company="示例科技")
    assert result.type is RecruiterType.HR


def test_mismatched_organization_is_inferred_headhunter_below_threshold() -> None:
    """A deduced agency is reported, but is too weak to drive hard routing."""
    result = classify(
        name="某某",
        title="示例咨询",
        organization="示例人才咨询",
        hiring_company="另一家公司",
    )

    assert result.type is RecruiterType.HEADHUNTER
    assert result.type_confidence < DEFAULT_ROUTING_THRESHOLD
    assert not is_routable(result)
    assert "organization_differs_from_hiring_company" in result.type_signals


def test_no_signal_yields_unknown_and_never_routes() -> None:
    result = classify(name="某某")

    assert result.type is RecruiterType.UNKNOWN
    assert result.type_confidence == 0.0
    assert result.type_signals == []
    assert not is_routable(result)


def test_unknown_never_routes_even_at_a_zero_threshold() -> None:
    """A caller must not be able to relax the gate into guessing."""
    result = classify(name="某某")
    assert not is_routable(result, threshold=0.0)


def test_classification_is_reported_with_its_signals_for_audit() -> None:
    result = classify(
        name="许先生", title="猎头 · 某咨询", organization="某咨询", hiring_company="用人单位"
    )
    assert result.type_signals, "a routing decision must explain itself"
