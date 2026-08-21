# Architecture invariants

```text
CandidateProfile != Resume
Evidence is the source of truth
JobSource != Job Intelligence
Job Match != Resume Compatibility
Resume Tailoring != Fact Generation
Preview != Approval
Approval != Send
Platform Connector != Domain Core
Search != Apply
Review != Auto Promote
CAPTCHA != Retry
```

Irreversible operations are separate capabilities. Domain code cannot depend on DOM selectors, browser profiles, platform SDK models, or connector internals.
