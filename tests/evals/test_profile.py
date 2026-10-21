from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from jobagent.evals.profile import next_profile_version, profile_digest
from jobagent.schemas.profile import ProfileField, ProfileSnapshot

AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)


def fields(**texts: str) -> list[ProfileField]:
    return [ProfileField(name=name, text=text) for name, text in texts.items()]


def snapshot(snapshot_id: str, at: datetime, **texts: str) -> ProfileSnapshot:
    kept = fields(**texts)
    return ProfileSnapshot(
        snapshot_id=snapshot_id,
        platform="boss",
        captured_at=at,
        fields=kept,
        digest=profile_digest(kept),
    )


def test_the_digest_ignores_field_order_but_not_wording() -> None:
    one = profile_digest(fields(advantage="主导 Agent 产品", work="某公司"))
    two = profile_digest(list(reversed(fields(advantage="主导 Agent 产品", work="某公司"))))

    assert one == two
    assert one != profile_digest(fields(advantage="参与 Agent 产品", work="某公司"))


def test_a_profile_names_each_field_once() -> None:
    with pytest.raises(ValidationError):
        ProfileSnapshot(
            snapshot_id="PROFSNAP_A",
            platform="boss",
            captured_at=AT,
            fields=fields(advantage="a") + fields(advantage="b"),
            digest=profile_digest(fields(advantage="a")),
        )


def test_the_first_profile_seen_is_the_baseline() -> None:
    first = snapshot("PROFSNAP_A", AT, advantage="主导 Agent 产品")

    version = next_profile_version(None, None, first)

    assert version is not None and version.origin == "baseline"
    assert version.effective_at == AT and version.snapshot_id == "PROFSNAP_A"
    assert version.previous_version_id is None


def test_an_unchanged_profile_is_no_new_version() -> None:
    first = snapshot("PROFSNAP_A", AT, advantage="主导 Agent 产品")
    base = next_profile_version(None, None, first)
    again = snapshot("PROFSNAP_B", AT + timedelta(days=1), advantage="主导 Agent 产品")

    assert next_profile_version(base, first, again) is None


def test_a_change_nobody_here_made_is_an_external_version_naming_its_fields() -> None:
    first = snapshot("PROFSNAP_A", AT, advantage="主导 Agent 产品", work="某公司")
    base = next_profile_version(None, None, first)
    later = AT + timedelta(days=2)
    changed = snapshot("PROFSNAP_B", later, advantage="主导金融 Agent 产品", project="新项目")

    version = next_profile_version(base, first, changed)

    assert version is not None and base is not None
    assert version.origin == "external"
    assert version.changed_fields == ["advantage", "project", "work"]
    assert version.previous_version_id == base.version_id
    assert version.effective_at == later
