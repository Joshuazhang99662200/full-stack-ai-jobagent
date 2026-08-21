# Job intelligence

Normalize the complete JD into atomic requirements and preserve source spans. Run deterministic hard filters before model-based matching. Return `PASS`, `REVIEW`, or `REJECT`; every reject requires a stable rule ID and explanation.

Matching reports dimension scores, strengths, partial matches, hard gaps, uncertainties, and evidence IDs. A bare percentage is invalid. Preserve all source provenance when deduplicating equivalent jobs.
