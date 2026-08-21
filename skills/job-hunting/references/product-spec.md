# Product contract

Build atomic, composable, testable, and auditable job-hunting capabilities for coding agents, CLI, MCP, and Python callers. The intended workflow is resume onboarding, adaptive evidence interview, target confirmation, multi-source job search, full JD retrieval, dedupe, hard filtering, explainable matching, evidence-grounded resume optimization, message generation, human review, digest-bound approval, delivery, compatibility clustering, batch approval, sequential batch delivery, and audit feedback.

The product is an evidence-grounded, human-approved job hunting agent. It is not an automatic mass-application bot.

The first complete workflow must run offline through `MockJobSource`. At least one later real connector must search, fetch full JD, retrieve recruiter details when available, preview, and submit only after valid approval.

The local-first baseline is Python 3.11+, Pydantic v2, Typer, SQLite, and pytest. Domain logic stays ordinary Python and does not initially depend on LangChain or LangGraph.

Private resumes, contact details, browser profiles, cookies, session tokens, secrets, local databases, and generated variants remain outside Git.
