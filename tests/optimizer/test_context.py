from jobagent.optimizer.context import select_evidence
from jobagent.schemas.jobs import JobRequirementProfile
from jobagent.schemas.optimizer import BaseResumeDocument, BaseResumeItem
from tests.optimizer.test_verification import evidence


def test_context_selects_references_and_terms_and_records_omissions():
    base = BaseResumeDocument(
        id="base",
        language="en",
        source_digest="sha256:test",
        items=[
            BaseResumeItem(
                id="ITEM_1", section="experience", text="migration", evidence_ids=["EVID_A"]
            ),
        ],
    )
    related = evidence("EVID_B").model_copy(update={"skills": ["Python"]})
    unrelated = evidence("EVID_C").model_copy(update={"statement": "Speaks French."})
    unknown = evidence("EVID_D", confirmed=False).model_copy(update={"skills": ["Python"]})
    selected, omitted = select_evidence(
        [unrelated, unknown, related, evidence()],
        JobRequirementProfile(job_id="JOB_1", skills=["Python"]),
        base,
    )
    assert [e.id for e in selected] == ["EVID_A", "EVID_B"]
    assert omitted == ["EVID_C"]
