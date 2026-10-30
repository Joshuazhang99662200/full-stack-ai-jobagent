"""Provider-neutral whole-message generation followed by fresh semantic review."""

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningOutputT, ReasoningProvider
from jobagent.errors import InvalidProviderOutputError
from jobagent.outreach.rules import first_greeting_problems
from jobagent.schemas.greeting import (
    GreetingAttempt,
    GreetingDraft,
    GreetingReport,
    GreetingRequest,
    GreetingReview,
)
from jobagent.schemas.outreach import OutreachDraft, OutreachSourceBinding

DRAFT_PROMPT = "greeting.ai.draft.v1"
REVIEW_PROMPT = "greeting.ai.review.v1"


def content_digest(value: object) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


class GreetingGenerator:
    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def generate(self, request: GreetingRequest) -> GreetingReport:
        request = GreetingRequest.model_validate(request.model_dump())
        payload = request.model_dump(mode="json")
        identity = content_digest(payload)
        attempts: list[GreetingAttempt] = []
        revision: dict[str, Any] | None = None
        for _ in range(2):
            context: dict[str, Any] = {"request": payload, "input_digest": identity}
            if revision is not None:
                context["revision"] = revision
            draft = self._produce(
                prompt_id=DRAFT_PROMPT, context=context, output_type=GreetingDraft,
            )
            self._validate_draft(request, draft, identity)
            problems = first_greeting_problems(draft.text)
            if attempts and draft.text == attempts[-1].draft.text:
                problems.append("unchanged_revision")
            review: GreetingReview | None = None
            if not problems:
                # The reviewer never receives the author's angle or previous verdicts.
                review_context = {
                    "request": payload, "input_digest": identity,
                    "draft_digest": content_digest(draft.model_dump(mode="json")),
                    "draft": draft.model_dump(mode="json", exclude={"angle"}),
                }
                review = self._produce(
                    prompt_id=REVIEW_PROMPT, context=review_context, output_type=GreetingReview,
                )
                if (review.input_digest != identity
                        or review.draft_digest != review_context["draft_digest"]):
                    raise InvalidProviderOutputError("Greeting review has stale source digests.")
                problems.extend(self._review_problems(draft, review))
            attempts.append(GreetingAttempt(draft=draft, review=review, problems=problems))
            if not problems:
                break
            revision = {"draft": draft.model_dump(mode="json"), "problems": problems}
        passed = not attempts[-1].problems
        outreach = None
        if passed and request.job is not None:
            draft = attempts[-1].draft
            outreach = OutreachDraft(
                job_id=request.job.job_id, platform=request.job.platform, text=draft.text,
                evidence_ids=sorted({i for claim in draft.claims for i in claim.evidence_ids}),
                variant=request.policy_version, hook_requirement="\n".join(draft.jd_spans),
                source_binding=OutreachSourceBinding(
                    candidate_id=request.candidate_id,
                    evidence_ids=[e.id for e in request.evidence],
                    evidence_digest=content_digest(payload["evidence"]),
                    job_digest=content_digest(request.job.model_dump(mode="json")),
                    text_digest=content_digest(draft.text), policy_digest=request.policy_digest,
                ),
            )
        return GreetingReport(
            candidate_id=request.candidate_id, mode=request.mode, input_digest=identity,
            evidence_digest=content_digest(payload["evidence"]),
            status="passed" if passed else "rejected", attempts=attempts, outreach_draft=outreach,
        )

    def _produce(
        self, *, prompt_id: str, context: dict[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        try:
            raw = self.provider.generate(
                prompt_id=prompt_id, context=context, output_type=output_type,
            )
            return output_type.model_validate(raw.model_dump())
        except (ValidationError, AttributeError, TypeError):
            raise InvalidProviderOutputError(
                "Greeting provider returned an invalid structured proposal.",
                details={"prompt_id": prompt_id},
            ) from None

    @staticmethod
    def _validate_draft(request: GreetingRequest, draft: GreetingDraft, identity: str) -> None:
        if draft.input_digest != identity:
            raise InvalidProviderOutputError("Greeting draft has a stale input digest.")
        available = {e.id for e in request.evidence}
        occupied: set[int] = set()
        for claim in draft.claims:
            if (claim.text not in draft.text or not set(claim.evidence_ids) <= available
                    or len(set(claim.evidence_ids)) != len(claim.evidence_ids)):
                raise InvalidProviderOutputError("Greeting claim has an invalid source or span.")
            start = draft.text.index(claim.text)
            positions = set(range(start, start + len(claim.text)))
            if occupied & positions:
                raise InvalidProviderOutputError("Greeting claim spans overlap or repeat.")
            occupied.update(positions)
        if request.job:
            if not draft.jd_spans or any(s not in request.job.jd_raw for s in draft.jd_spans):
                raise InvalidProviderOutputError("Greeting target quotations are not in the JD.")
        elif draft.jd_spans:
            raise InvalidProviderOutputError("Default greetings cannot invent a target JD.")

    @staticmethod
    def _review_problems(draft: GreetingDraft, review: GreetingReview) -> list[str]:
        problems = list(review.issues)
        actual = [item.text for item in review.claims]
        expected = [claim.text for claim in draft.claims]
        if len(actual) != len(expected) or set(actual) != set(expected):
            problems.append("review_claim_coverage")
        problems.extend(
            f"claim:{item.verdict}:{item.reason}" for item in review.claims
            if item.verdict != "supported"
        )
        for field in (
            "full_text_supported", "no_missing_claims", "target_relevant",
            "style_ok", "conflicts_resolved",
        ):
            if not getattr(review, field):
                problems.append(field)
        return problems
