# Evidence policy

Every substantive claim must cite one or more `EVID_*` identifiers. Preserve source, confidence, confirmation state, chronology, ownership, scope, and metric meaning.

Allowed transformations include faithful paraphrase, compression, reordering, translation, emphasis, omission, and combination that does not broaden meaning.

Do not create metrics, strengthen participation into leadership, turn conceptual knowledge into production experience, or represent inferred evidence as fact. Missing evidence returns `MISSING_EVIDENCE` and may propose an interview question.

## Candidate Core enforcement

- Resume reasoning output must be a valid `CandidateDraft` bound to the same Candidate ID and exact `RESUME_*:page:N` sources.
- A provider response carrying `user_confirmed=true`, a different Candidate ID, a different Resume ID, or a nonexistent page is invalid provider output.
- `CandidateEvidenceService.add_draft` refuses preconfirmed input.
- `CandidateEvidenceService.confirm` is the only Candidate Core operation that promotes admissible evidence to confirmed state; weak evidence is rejected.
- A user edit changes provenance to `user_edit`, preserves the Evidence ID, and returns the item to unconfirmed state.
- An interview answer has `interview` provenance and remains unconfirmed. A skipped question creates no EvidenceItem.

The local SQLite repository stores private operational records, but logs and CLI errors must not echo resume bodies or raw provider payloads.
