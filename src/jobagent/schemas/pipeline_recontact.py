"""Bind an existing human-approved conversation reply to a new contact round."""

from pydantic import Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import NonEmptyString
from jobagent.schemas.pipeline import PipelineContract


class PipelineBindReplyInput(PipelineContract):
    event_id: NonEmptyString
    candidate_id: CandidateId
    pipeline_id: NonEmptyString
    expected_version: int = Field(ge=1)
    conversation_id: NonEmptyString
    approval_event_id: NonEmptyString
