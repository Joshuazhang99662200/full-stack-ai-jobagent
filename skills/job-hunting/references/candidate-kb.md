# Candidate knowledge base

Treat the candidate knowledge base as canonical and every resume as a projection. Keep profile facts, evidence, preferences, constraints, search strategy, and unknown fields separate.

Adaptive interview questions target one current gap at a time. Rank gaps by ambiguity, evidence weakness, target-role relevance, and expected information gain. The user may skip; unknown remains a valid state.

Answers create draft evidence. Only explicit or user-confirmed admissible evidence may support a final substantive resume claim.

## Implemented Candidate Core routing

Use the atomic Python services when composing a workflow:

- `PdfResumeParser.parse` extracts ordered PDF pages and a SHA-256 source digest.
- `ReasoningCandidateDraftExtractor.extract` requests `CandidateDraft` with prompt ID `candidate.extract_draft.v1` and revalidates candidate and page provenance.
- `CandidateOnboardingService.ingest_resume` performs parse, extract, then one transactional repository write.
- `GapDetector.detect` derives current gaps from profile, evidence, unknowns, and target role.
- `AdaptiveInterview.next_question` returns zero or one question and respects recent gap IDs.
- `AdaptiveInterview.record_answer` returns an `InterviewOutcome`; an answer contains unconfirmed interview evidence, while a skip contains only an event.
- `CandidateReadinessService.evaluate` reports descriptive completeness and evidence readiness.

For local operator workflows, route to `jobagent candidate ingest`, `import-draft`, `question`, `answer`, `confirm`, and `status`. Commands emit JSON and use SQLite through `--database`.

Do not treat PDF text extraction as fact interpretation. If no production reasoning provider is configured, use a human-reviewed `CandidateDraft` JSON import instead of heuristic claim generation.
