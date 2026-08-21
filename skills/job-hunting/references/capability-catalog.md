# Capability catalog

- Candidate: `parse_resume`, `detect_gaps`, `ask_question`, `update_profile`, `add_evidence`.
- Jobs: `search`, `fetch`, `normalize`, `dedupe`, `hard_filter`, `match`, `rank`.
- Resume: `retrieve_evidence`, `plan`, `tailor`, `verify`, `render`, `diff`.
- Message: `generate`.
- Application: `prepare`, `preview`, `approve`, `send`, `audit`.
- Cluster: `resume_compatibility`.

Each capability has typed input and output contracts, explicit errors, no hidden side effects, independent tests, and a direct Python-callable boundary.
