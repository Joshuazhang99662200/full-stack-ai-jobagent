"""Artifact refresh identifies a bound pipeline; the caller supplies no artifact text."""

from pydantic import Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, NonEmptyString


class PipelineSyncRequest(ContractModel):
    event_id: NonEmptyString
    pipeline_id: NonEmptyString
    candidate_id: CandidateId
    expected_version: int = Field(ge=1)
