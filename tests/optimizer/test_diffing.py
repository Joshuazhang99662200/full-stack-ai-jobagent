"""The diff is derived from the documents, so it cannot omit an awkward edit."""

from jobagent.optimizer.diffing import ResumeDiffBuilder
from jobagent.schemas.optimizer import BaseResumeItem, OptimizedResumeItem, RewriteOperation


def base(item_id: str = "ITEM_1", text: str = "Participated in a migration.") -> BaseResumeItem:
    return BaseResumeItem(id=item_id, section="经历", text=text, evidence_ids=["EVID_A"])


def optimized(
    item_id: str = "ITEM_1",
    text: str = "Migrated the platform.",
    *,
    sources: list[str] | None = None,
    operations: list[RewriteOperation] | None = None,
    requirement_ids: list[str] | None = None,
) -> OptimizedResumeItem:
    return OptimizedResumeItem(
        id=item_id,
        section="经历",
        text=text,
        evidence_ids=["EVID_A"],
        requirement_ids=requirement_ids if requirement_ids is not None else ["REQ_A"],
        source_resume_item_ids=sources if sources is not None else [item_id],
        rewrite_operations=operations
        if operations is not None
        else [RewriteOperation.PARAPHRASE],
    )


def test_unchanged_text_produces_no_diff_entry() -> None:
    text = "Participated in a migration."
    diff = ResumeDiffBuilder().build([base(text=text)], [optimized(text=text)])
    assert diff.items == []


def test_rewritten_item_records_both_sides_and_its_operations() -> None:
    diff = ResumeDiffBuilder().build([base()], [optimized()])

    assert len(diff.items) == 1
    entry = diff.items[0]
    assert entry.original == "Participated in a migration."
    assert entry.optimized == "Migrated the platform."
    assert entry.rewrite_operations == [RewriteOperation.PARAPHRASE]
    assert "paraphrase" in entry.reason


def test_dropped_item_is_surfaced_as_an_omission() -> None:
    """A reviewer has to see what was removed, not only what was reworded."""
    diff = ResumeDiffBuilder().build([base("ITEM_1"), base("ITEM_2")], [optimized("ITEM_1")])

    omissions = [item for item in diff.items if item.optimized is None]
    assert len(omissions) == 1
    assert omissions[0].rewrite_operations == [RewriteOperation.OMIT]
    assert omissions[0].risk_notes


def test_new_item_without_a_source_is_marked_as_assembled() -> None:
    diff = ResumeDiffBuilder().build([], [optimized("ITEM_NEW", sources=[])])

    assert diff.items[0].original is None
    assert "New item" in diff.items[0].reason


def test_undeclared_operation_is_flagged_as_a_risk() -> None:
    diff = ResumeDiffBuilder().build([base()], [optimized(operations=[])])
    assert any("No rewrite operation declared" in note for note in diff.items[0].risk_notes)


def test_large_growth_is_flagged_as_a_risk() -> None:
    """Growth is where unevidenced detail tends to creep in."""
    long_text = "Migrated the platform, cut latency, mentored the team, and owned the roadmap."
    diff = ResumeDiffBuilder().build([base()], [optimized(text=long_text)])
    assert any("substantially longer" in note for note in diff.items[0].risk_notes)


def test_item_not_tied_to_a_requirement_is_flagged() -> None:
    diff = ResumeDiffBuilder().build([base()], [optimized(requirement_ids=[])])
    assert any("not tied to any job requirement" in note for note in diff.items[0].risk_notes)


def test_combined_sources_are_joined_in_the_original_side() -> None:
    diff = ResumeDiffBuilder().build(
        [base("ITEM_1", "First."), base("ITEM_2", "Second.")],
        [
            optimized(
                "ITEM_1",
                text="First and second.",
                sources=["ITEM_1", "ITEM_2"],
                operations=[RewriteOperation.COMBINE],
            )
        ],
    )

    entries = [item for item in diff.items if item.optimized is not None]
    assert entries[0].original == "First.\nSecond."
    # Both sources were consumed, so neither may also appear as an omission.
    assert all(item.optimized is not None for item in diff.items)
