import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobagent.jobs.jd_snapshot import text_digest

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
STATES = [
    "draft_pending",
    "greeting_sent",
    "greeting_read",
    "initial_contact",
    "resume_requested",
    "resume_sent",
    "interview_pending",
    "interviewed",
    "abandoned",
]
EDGES = {
    ("draft_pending", "greeting_sent"),
    ("greeting_sent", "greeting_read"),
    ("greeting_sent", "abandoned"),
    ("greeting_read", "initial_contact"),
    ("greeting_read", "abandoned"),
    ("initial_contact", "resume_requested"),
    ("initial_contact", "interview_pending"),
    ("initial_contact", "abandoned"),
    ("resume_requested", "resume_sent"),
    ("resume_requested", "abandoned"),
    ("resume_sent", "interview_pending"),
    ("resume_sent", "abandoned"),
    ("interview_pending", "interviewed"),
    ("interview_pending", "abandoned"),
    ("interviewed", "abandoned"),
}


def row(**changes):
    from jobagent.schemas.pipeline import PipelineJob

    data = dict(
        pipeline_id="PIPE_0123456789ABCDEF",
        candidate_id="CAND_DEMO",
        job_id="boss-synthetic",
        platform="boss",
        job_url="https://www.zhipin.com/job_detail/synthetic.html",
        title="Synthetic designer",
        company="Synthetic company",
        salary_raw="18-25K",
        salary_min_k=18,
        salary_max_k=25,
        salary_verified="pass",
        jd_points=json.dumps(["Design"]),
        pipeline_state="draft_pending",
        state_changed_at=NOW,
        entered_at=NOW,
        updated_at=NOW,
    )
    data.update(changes)
    return PipelineJob.model_validate(data)


def test_pipeline_master_has_exact_contract_fields_and_no_synonyms():
    record = row()
    fields = set(type(record).model_fields) - {"schema_version"}
    assert fields == set(
        [
            "pipeline_id",
            "candidate_id",
            "job_id",
            "platform",
            "job_url",
            "title",
            "company",
            "location",
            "salary_raw",
            "salary_min_k",
            "salary_max_k",
            "salary_verified",
            "jd_text",
            "jd_text_hash",
            "jd_points",
            "draft_greeting",
            "draft_version",
            "draft_digest",
            "sent_greeting",
            "sent_text_hash",
            "sent_at",
            "send_readback",
            "resume_requested",
            "resume_requested_at",
            "resume_request_evidence",
            "resume_version",
            "resume_file_id",
            "resume_sent_at",
            "pipeline_state",
            "state_reason",
            "state_changed_at",
            "entered_at",
            "updated_at",
        ]
    )
    assert not {"status", "stage", "phase", "is_read", "has_reply"} & fields
    assert record.resume_requested is False and record.sent_at is None


@pytest.mark.parametrize("source", STATES)
@pytest.mark.parametrize("target", STATES)
def test_model_rejects_every_forbidden_jump(source, target):
    from jobagent.schemas.pipeline import PipelineTransition

    reason = "user_abandoned" if target == "abandoned" else "normal"
    data = dict(
        event_id="EVENT",
        pipeline_id="PIPE_0123456789ABCDEF",
        candidate_id="CAND_DEMO",
        expected_version=1,
        from_state=source,
        to_state=target,
        changed_at=NOW,
        evidence_kind="owner_message" if target == "abandoned" else "conversation_message",
        evidence_reference="PRIVATE_EVIDENCE",
        reason_code=reason,
    )
    if (source, target) in EDGES:
        assert PipelineTransition.model_validate(data).to_state == target
    else:
        with pytest.raises(ValidationError):
            PipelineTransition.model_validate(data)


def test_hash_nullability_points_and_resume_fields_are_not_interchangeable():
    for changes in [
        dict(jd_text_hash=text_digest("summary")),
        dict(jd_text="full", jd_text_hash=text_digest("different")),
        dict(jd_points=json.dumps(["one", "two", "three", "four"])),
        dict(draft_greeting="draft", draft_digest=text_digest("draft")),
        dict(sent_greeting="sent", sent_text_hash=text_digest("different")),
        dict(resume_requested_at=NOW),
        dict(resume_file_id="DEFAULT_RESUME"),
        dict(state_reason="freeform reason"),
        dict(entered_at=NOW.replace(tzinfo=None)),
    ]:
        with pytest.raises(ValidationError):
            row(**changes)
    assert row(jd_text="full", jd_text_hash=text_digest("full")).jd_text == "full"


def test_unread_count_cannot_confirm_transitions_and_interviewed_has_limited_closure():
    from jobagent.schemas.pipeline import PipelineTransition

    base = dict(
        event_id="EVENT",
        pipeline_id="PIPE_0123456789ABCDEF",
        candidate_id="CAND_DEMO",
        expected_version=1,
        from_state="greeting_sent",
        to_state="greeting_read",
        changed_at=NOW,
        evidence_kind="unread_count",
        evidence_reference="BADGE",
        reason_code="normal",
    )
    with pytest.raises(ValidationError):
        PipelineTransition.model_validate(base)
    with pytest.raises(ValidationError):
        PipelineTransition.model_validate(
            {
                **base,
                "from_state": "interviewed",
                "to_state": "abandoned",
                "evidence_kind": "conversation_message",
                "reason_code": "employer_rejected",
            }
        )
