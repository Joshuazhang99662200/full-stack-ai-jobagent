import pytest

from jobagent.jobs.jd_snapshot import text_digest
from tests.storage.test_job_intake import NOW

CATEGORIES = [
    "fact_correction",
    "job_routing",
    "business_specificity",
    "technical_accuracy",
    "style",
    "motivation",
]


def sample(number=1, **changes):
    initial, final = "Initial claim.", "Revised claim."
    payload = dict(
        event_id=f"DIFF_{number}",
        candidate_id="CAND_DEMO",
        job_id=f"JOB_DEMO_{number}",
        draft_reference=f"DRAFT_{number}",
        occurred_at=NOW,
        source_reference="PRIVATE_CARD",
        initial_text=initial,
        final_text=final,
        initial_hash=text_digest(initial),
        final_hash=text_digest(final),
        classifier_reference="HOST_PROPOSAL",
        labels=[
            dict(
                category="fact_correction",
                initial_start=0,
                initial_end=7,
                final_start=0,
                final_end=7,
            )
        ],
    )
    payload.update(changes)
    return payload


@pytest.mark.parametrize("category", CATEGORIES)
def test_all_six_categories_require_exact_changed_span_evidence(category):
    from jobagent.jobs.message_diff import compare
    from jobagent.schemas.message_diff import MessageDiffInput

    payload = sample()
    payload["labels"][0]["category"] = category
    result = compare(MessageDiffInput.model_validate(payload))
    assert result.categories == [category] and result.changed
    assert not result.send_proof_verified
    assert result.classification_status == "proposed"


def test_multilabel_unknown_and_unchanged_are_separate():
    from jobagent.jobs.message_diff import compare
    from jobagent.schemas.message_diff import MessageDiffInput

    payload = sample()
    payload["labels"].append({**payload["labels"][0], "category": "job_routing"})
    assert len(compare(MessageDiffInput.model_validate(payload)).categories) == 2
    unknown = compare(MessageDiffInput.model_validate(sample(labels=[], classifier_reference=None)))
    assert (
        unknown.changed
        and unknown.categories == []
        and unknown.classification_status == "needs_classification"
    )
    unchanged = sample(
        final_text="Initial claim.", final_hash=text_digest("Initial claim."), labels=[]
    )
    result = compare(MessageDiffInput.model_validate(unchanged))
    assert not result.changed and result.categories == []


def test_only_punctuation_or_whitespace_may_auto_classify_style():
    from jobagent.jobs.message_diff import compare
    from jobagent.schemas.message_diff import MessageDiffInput

    payload = sample(
        final_text="Initial  claim!", final_hash=text_digest("Initial  claim!"), labels=[]
    )
    assert compare(MessageDiffInput.model_validate(payload)).categories == ["style"]


def test_wrong_hash_out_of_range_and_unchanged_span_cannot_support_category():
    from jobagent.errors import ContractValidationError
    from jobagent.jobs.message_diff import compare
    from jobagent.schemas.message_diff import MessageDiffInput

    for payload in [
        sample(initial_hash=text_digest("wrong")),
        sample(
            labels=[
                dict(
                    category="style", initial_start=100, initial_end=101, final_start=0, final_end=1
                )
            ]
        ),
        sample(
            labels=[
                dict(category="style", initial_start=8, initial_end=13, final_start=8, final_end=13)
            ]
        ),
    ]:
        with pytest.raises(ContractValidationError):
            compare(MessageDiffInput.model_validate(payload))
