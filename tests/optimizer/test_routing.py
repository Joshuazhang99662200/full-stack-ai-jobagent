"""Routing is skill-internal judgement, driven by what fetch actually observed."""

import pytest

from jobagent.jobs.recruiter import RecruiterClassifier
from jobagent.optimizer.routing import LENS_POLICIES, RewriteLens, RewriteLensRouter
from jobagent.schemas.jobs import RecruiterInfo, RecruiterType
from jobagent.skill_resources import default_skill_root


def route(**kwargs: str | None) -> object:
    return RewriteLensRouter().select(RecruiterClassifier().classify(**kwargs))  # type: ignore[arg-type]


def test_platform_labelled_headhunter_routes_to_the_headhunter_lens() -> None:
    selection = route(
        name="许先生",
        title="猎头 · 北京优九人才咨询有限公司",
        organization="北京优九人才咨询有限公司",
        hiring_company="某北京基金/证券/期货公司",
    )

    assert selection.lens is RewriteLens.HEADHUNTER  # type: ignore[attr-defined]
    assert "platform_label:猎头" in selection.signals  # type: ignore[attr-defined]
    assert selection.declined_lens is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("title", "expected"),
    [("HRBP", RewriteLens.INTERNAL_HR), ("技术总监", RewriteLens.HIRING_MANAGER)],
)
def test_titles_route_to_their_lens(title: str, expected: RewriteLens) -> None:
    selection = route(name="某", title=title, organization="示例科技", hiring_company="示例科技")
    assert selection.lens is expected  # type: ignore[attr-defined]


def test_employer_side_but_unspecified_falls_back_instead_of_guessing() -> None:
    """internal_unspecified is an honest non-answer; it must not become a guess."""
    selection = route(
        name="孙女士", title="宁波银行", organization="宁波银行", hiring_company="宁波银行"
    )

    assert selection.lens is RewriteLens.GENERAL  # type: ignore[attr-defined]
    assert selection.declined_lens is None  # type: ignore[attr-defined]
    assert "internal_unspecified" in selection.reason  # type: ignore[attr-defined]


def test_low_confidence_falls_back_but_records_what_it_declined() -> None:
    selection = route(
        name="某", title="示例咨询", organization="示例人才咨询", hiring_company="另一家公司"
    )

    assert selection.lens is RewriteLens.GENERAL  # type: ignore[attr-defined]
    assert selection.declined_lens is RewriteLens.HEADHUNTER  # type: ignore[attr-defined]
    assert "below the routing threshold" in selection.reason  # type: ignore[attr-defined]


def test_no_recruiter_routes_to_general() -> None:
    selection = RewriteLensRouter().select(None)
    assert selection.lens is RewriteLens.GENERAL
    assert selection.declined_lens is None


def test_unknown_recruiter_never_routes_to_a_targeted_lens() -> None:
    selection = RewriteLensRouter().select(RecruiterInfo(type=RecruiterType.UNKNOWN))
    assert selection.lens is RewriteLens.GENERAL


def test_every_lens_names_a_policy_that_exists_in_the_skill() -> None:
    root = default_skill_root()
    for lens in RewriteLens:
        path = root / LENS_POLICIES[lens]
        assert path.is_file(), lens.value


def test_every_lens_policy_restates_the_shared_evidence_invariant() -> None:
    """A lens may change emphasis, never facts. Each body must say so."""
    root = default_skill_root()
    for lens in RewriteLens:
        body = (root / LENS_POLICIES[lens]).read_text(encoding="utf-8")
        if lens is RewriteLens.GENERAL:
            assert "同一批已确认证据" in body
            assert "绝不改变事实" in body
        else:
            # Targeted lenses defer to the shared invariant rather than restating it.
            assert "lens-general.md" in body
            assert "同一批已确认证据" in body


def test_routing_always_explains_itself() -> None:
    for selection in (
        RewriteLensRouter().select(None),
        route(name="许先生", title="猎头 · 某咨询", organization="某咨询", hiring_company="用人方"),
    ):
        assert selection.reason.strip()  # type: ignore[attr-defined]
        assert selection.policy_path.startswith("references/optimizer/")  # type: ignore[attr-defined]
