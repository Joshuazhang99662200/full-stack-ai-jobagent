"""Connect existing job reasoning contracts to the isolated local text runner."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from jobagent.bridge.codex_runner import CodexTextRunner
from jobagent.capabilities import ReasoningOutputT
from jobagent.errors import ContractValidationError
from jobagent.reasoning.job_matcher import is_admissible
from jobagent.reasoning.prompts import system_prompt
from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.coordinator import CodexTextRecord, CodexTextRequest
from jobagent.schemas.job_intelligence import RequirementMatchSet
from jobagent.schemas.jobs import JobRequirement, JobRequirementProfile

_EXTRACT = "job.requirements.extract.v1"
_MATCH = "job.match.evidence.v1"
_FIELDS = {
    _EXTRACT: {"job_id", "title", "company", "location", "jd_raw"},
    _MATCH: {"job_id", "candidate_id", "requirements", "evidence"},
}


class CodexJobReasoningProvider:
    """Only requirements and evidence mappings; scoring and approval remain outside."""

    def __init__(self, runner: CodexTextRunner) -> None:
        self.runner = runner

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        expected = {_EXTRACT: JobRequirementProfile, _MATCH: RequirementMatchSet}
        if prompt_id not in expected or output_type is not expected[prompt_id]:
            raise ContractValidationError("This text provider only supports typed job reasoning.")
        if set(context) != _FIELDS[prompt_id]:
            raise ContractValidationError(
                "The job reasoning context has missing or unexpected fields."
            )
        prompt = system_prompt(prompt_id)
        if prompt is None:
            raise ContractValidationError("The job reasoning policy is unavailable.")
        if prompt_id == _EXTRACT:
            prompt += (
                "\n\nOutput contract clarification: every aggregate entry "
                "(must_have, nice_to_have, "
                "responsibilities, skills, domains, management, commercial, education, languages, "
                "location_constraints, risk_signals) must itself be an exact substring "
                "of an atomic "
                "requirement's statement or source_span. Do not introduce paraphrased categories "
                "only in aggregate fields. Keep all observed requirements in the atomic list, "
                "including hard constraints; risk judgments belong outside this extraction. "
                "Every source_span quotes jd_raw only; metadata is not JD source text."
            )
        try:
            self._validate_context(prompt_id, context)
            payload = (
                {key: context[key] for key in ("job_id", "jd_raw")}
                if prompt_id == _EXTRACT
                else dict(context)
            )
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
            identity = hashlib.sha256(
                (prompt_id + "\n" + prompt + "\n" + body).encode()
            ).hexdigest()
            request = CodexTextRequest(
                request_id="CTX_" + identity.upper(),
                instruction=prompt,
                records=[
                    CodexTextRecord(
                        record_id=str(context["job_id"]),
                        kind="jd" if prompt_id == _EXTRACT else "evidence",
                        text=body,
                    )
                ],
            )
        except (TypeError, ValueError, ValidationError):
            raise ContractValidationError(
                "Job reasoning input is not valid bounded text.",
                details={"prompt_id": prompt_id},
            ) from None
        return self.runner.run(request, output_type)

    @staticmethod
    def _validate_context(prompt_id: str, context: Mapping[str, Any]) -> None:
        string_fields = _FIELDS[_EXTRACT] if prompt_id == _EXTRACT else {"job_id", "candidate_id"}
        if any(not isinstance(context[key], str) for key in string_fields):
            raise ValueError("expected text fields")
        if prompt_id == _EXTRACT:
            return
        TypeAdapter(list[JobRequirement]).validate_python(context["requirements"])
        if not isinstance(context["evidence"], list):
            raise ValueError("expected evidence list")
        for row in context["evidence"]:
            if not isinstance(row, dict):
                raise ValueError("expected typed evidence")
            item = EvidenceItem.model_validate(
                {key: value for key, value in row.items() if key != "admissible"}
            )
            if row.get("admissible") is not is_admissible(item):
                raise ValueError("inconsistent evidence admissibility")
