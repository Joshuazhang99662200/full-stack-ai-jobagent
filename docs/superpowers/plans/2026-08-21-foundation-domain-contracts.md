# Foundation and Domain Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable, privacy-safe Python package containing the first stable JobAgent schemas, provider ports, architectural documentation, and progressively disclosed `job-hunting` Skill Context.

**Architecture:** The package uses Pydantic v2 contracts at domain boundaries and ports-and-adapters interfaces for providers. This phase contains contracts and documentation only: it introduces no connector automation, LLM calls, SQLite repositories, resume rewriting, approval mutation, or delivery behavior.

**Tech Stack:** Python 3.11+, Pydantic v2, Typer, pytest, Ruff, mypy, Markdown-based Codex skills

## Global Constraints

- Python runtime support begins at 3.11.
- Pydantic major version is 2; LangChain and LangGraph are not dependencies.
- Domain modules must not import browser automation, platform SDKs, Typer, or SQLite.
- `extra="forbid"` applies to serialized domain contracts.
- Every substantive resume claim must expose evidence IDs.
- Preview, approval, and send remain different schemas and capabilities.
- Candidate match and resume compatibility remain different types.
- Private resumes, contact exports, browser state, credentials, databases, and synced OSS caches are ignored by Git.
- Auto-JobHunter remains reference-only; no source or prompt text is copied.

---

## File Map

```text
pyproject.toml                              Packaging, dependencies, test/lint/type settings
.gitignore                                 Privacy and generated-artifact exclusions
.env.example                               Public configuration names without secrets
LICENSE                                    Apache-2.0 project license
README.md                                  Honest project positioning and phase-1 quickstart
src/jobagent/__init__.py                   Package version and public package marker
src/jobagent/py.typed                      PEP 561 marker
src/jobagent/errors.py                     Stable typed domain failures
src/jobagent/capabilities.py               Generic Capability, JobSource, ReasoningProvider ports
src/jobagent/schemas/common.py             Shared enums, IDs, time, source, money, provenance
src/jobagent/schemas/candidate.py          Candidate profile, evidence, gaps, preferences, constraints
src/jobagent/schemas/jobs.py               Normalized jobs, requirements, filters, matching
src/jobagent/schemas/optimizer.py          Plans, variants, claims, verification, diff, compatibility
src/jobagent/schemas/applications.py       Packages, digest-bound approvals, delivery results, audit
src/jobagent/schemas/__init__.py            Intentional schema exports
skills/job-hunting/SKILL.md                Skill entrypoint and context router
skills/job-hunting/agents/openai.yaml      Skill display metadata
skills/job-hunting/references/*.md         Focused on-demand domain context
skills/job-hunting/references/optimizer/*  Optimizer routing and quality gates
skills/job-hunting/references/oss/*        Verified reuse modes and source registry
docs/architecture.md                       Ports-and-adapters view and dependency rules
docs/domain-model.md                       Entity relationships and lifecycle rules
docs/oss-review.md                         License gate and verified reuse decisions
tests/test_package_metadata.py             Package bootstrap and privacy contract
tests/schemas/test_common.py               Shared schema validation
tests/schemas/test_candidate.py            Evidence and candidate contract tests
tests/schemas/test_jobs.py                 Job, filter, and match contract tests
tests/schemas/test_optimizer.py            Claim grounding and compatibility separation tests
tests/schemas/test_applications.py         Approval digest and audit contract tests
tests/test_capabilities.py                 Port shape and typed failure tests
tests/test_skill_context.py                Skill validation, routing links, and source-manifest tests
```

### Task 1: Package Bootstrap and Privacy Boundary

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `LICENSE`
- Create: `README.md`
- Create: `src/jobagent/__init__.py`
- Create: `src/jobagent/py.typed`
- Test: `tests/test_package_metadata.py`

**Interfaces:**
- Consumes: approved foundation design.
- Produces: importable `jobagent` package with `__version__ = "0.1.0"` and privacy exclusions used by every later task.

- [ ] **Step 1: Write failing package and privacy tests**

```python
from pathlib import Path

import jobagent


ROOT = Path(__file__).parents[1]


def test_package_has_version() -> None:
    assert jobagent.__version__ == "0.1.0"


def test_private_paths_are_ignored() -> None:
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in (
        ".env",
        "candidate/private/",
        "*.sqlite3",
        ".jobagent/cache/",
        ".jobagent/browser-profiles/",
    ):
        assert required in rules
```

- [ ] **Step 2: Run the test and confirm import failure**

Run: `python -m pytest tests/test_package_metadata.py -q`
Expected: FAIL because `jobagent` and `.gitignore` do not exist.

- [ ] **Step 3: Add packaging and privacy files**

`pyproject.toml` must declare:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "human-approved-jobagent"
version = "0.1.0"
description = "Evidence-grounded, human-approved AI job hunting capabilities"
readme = "README.md"
requires-python = ">=3.11"
license = { file = "LICENSE" }
dependencies = [
  "pydantic>=2.11,<3",
  "typer>=0.16,<1",
]

[project.optional-dependencies]
dev = [
  "mypy>=1.17,<2",
  "pytest>=8.4,<9",
  "ruff>=0.12,<1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers --strict-config"

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["jobagent"]

[tool.hatch.build.targets.wheel]
packages = ["src/jobagent"]
```

`.gitignore` must include Python build artifacts plus the exact private patterns asserted by the test. `README.md` must state “An evidence-grounded, human-approved AI job hunting agent” and explicitly reject automatic mass application. `LICENSE` must contain the unmodified Apache License 2.0 text. `.env.example` lists provider and connector variable names with blank values. `src/jobagent/__init__.py` contains `__version__ = "0.1.0"`.

- [ ] **Step 4: Install development dependencies and run the test**

Run: `python -m pip install -e ".[dev]"`
Expected: editable install succeeds.

Run: `python -m pytest tests/test_package_metadata.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit bootstrap**

```bash
git add pyproject.toml .gitignore .env.example LICENSE README.md src tests/test_package_metadata.py
git commit -m "build: bootstrap privacy-safe jobagent package"
```

### Task 2: Shared Schema Primitives and Typed Errors

**Files:**
- Create: `src/jobagent/schemas/common.py`
- Create: `src/jobagent/errors.py`
- Create: `src/jobagent/schemas/__init__.py`
- Test: `tests/schemas/test_common.py`

**Interfaces:**
- Consumes: Pydantic v2.
- Produces: `ContractModel`, `TimeRange`, `MoneyRange`, `SourceReference`, `ProvenanceRecord`, shared enums, and `JobAgentError` subclasses.

- [ ] **Step 1: Write failing common-contract tests**

```python
from datetime import date

import pytest
from pydantic import ValidationError

from jobagent.errors import MissingEvidenceError
from jobagent.schemas.common import SourceReference, SourceType, TimeRange


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourceReference(type=SourceType.RESUME, reference="page:1", surprise=True)


def test_time_range_rejects_reverse_dates() -> None:
    with pytest.raises(ValidationError):
        TimeRange(start=date(2025, 1, 1), end=date(2024, 1, 1))


def test_domain_error_has_stable_code() -> None:
    error = MissingEvidenceError("RAG implementation evidence is absent")
    assert error.code == "MISSING_EVIDENCE"
```

- [ ] **Step 2: Run the tests and confirm missing modules**

Run: `python -m pytest tests/schemas/test_common.py -q`
Expected: FAIL because schema and error modules do not exist.

- [ ] **Step 3: Implement shared contracts and errors**

Use `ConfigDict(extra="forbid", validate_assignment=True)` on `ContractModel`. Validate `TimeRange.end >= TimeRange.start` when both exist. Define `SourceType` values `resume`, `interview`, `user_edit`, `connector`, and `system`. Define errors with constructor `JobAgentError(message: str, *, details: Mapping[str, Any] | None = None)` and stable class-level codes for validation, missing evidence, conflict, policy rejection, user intervention, provider output, stale approval, and storage failure.

- [ ] **Step 4: Run common tests**

Run: `python -m pytest tests/schemas/test_common.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit common contracts**

```bash
git add src/jobagent/errors.py src/jobagent/schemas tests/schemas/test_common.py
git commit -m "feat: add shared domain contract primitives"
```

### Task 3: Candidate and Evidence Contracts

**Files:**
- Create: `src/jobagent/schemas/candidate.py`
- Modify: `src/jobagent/schemas/__init__.py`
- Test: `tests/schemas/test_candidate.py`

**Interfaces:**
- Consumes: `ContractModel`, `SourceReference`, `TimeRange`.
- Produces: candidate facts, `EvidenceItem`, `CandidateProfile`, preferences, constraints, unknown fields, gaps, and readiness report.

- [ ] **Step 1: Write failing evidence tests**

```python
import pytest
from pydantic import ValidationError

from jobagent.schemas.candidate import Confidence, EvidenceItem, EvidenceType
from jobagent.schemas.common import SourceReference, SourceType


def test_evidence_requires_statement_and_source() -> None:
    item = EvidenceItem(
        id="EVID_001",
        type=EvidenceType.ACHIEVEMENT,
        statement="Reduced review time by 30%.",
        source=SourceReference(type=SourceType.RESUME, reference="page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=True,
    )
    assert item.id == "EVID_001"


def test_confirmed_evidence_cannot_be_weak() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            id="EVID_002",
            type=EvidenceType.SKILL,
            statement="May know RAG.",
            source=SourceReference(type=SourceType.RESUME, reference="page:2"),
            confidence=Confidence.WEAK,
            user_confirmed=True,
        )
```

- [ ] **Step 2: Run and confirm missing candidate contracts**

Run: `python -m pytest tests/schemas/test_candidate.py -q`
Expected: FAIL with missing `candidate` module.

- [ ] **Step 3: Implement candidate contracts**

Define the approved candidate types as focused Pydantic models. `EvidenceItem` includes `id`, `type`, `entity`, `statement`, `skills`, `domains`, `metrics`, `time_range`, `source`, `confidence`, and `user_confirmed`. A model validator rejects `user_confirmed=True` with `confidence=weak`. IDs must match `EVID_[A-Z0-9_]+`. `CandidateProfile` aggregates experiences, education, skills, projects, achievements, domain, management, commercial, languages, certifications, and unknown fields without embedding resume formatting.

- [ ] **Step 4: Run candidate tests**

Run: `python -m pytest tests/schemas/test_candidate.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit candidate contracts**

```bash
git add src/jobagent/schemas/candidate.py src/jobagent/schemas/__init__.py tests/schemas/test_candidate.py
git commit -m "feat: define candidate evidence contracts"
```

### Task 4: Job, Filter, and Match Contracts

**Files:**
- Create: `src/jobagent/schemas/jobs.py`
- Modify: `src/jobagent/schemas/__init__.py`
- Test: `tests/schemas/test_jobs.py`

**Interfaces:**
- Consumes: shared contract types and evidence ID strings.
- Produces: `NormalizedJob`, `JobRequirementProfile`, `HardFilterResult`, `MatchResult`, and provenance-preserving source records.

- [ ] **Step 1: Write failing job-contract tests**

```python
import pytest
from pydantic import ValidationError

from jobagent.schemas.jobs import FilterDecision, HardFilterResult, MatchResult, MatchDecision


def test_reject_requires_deterministic_reasons() -> None:
    with pytest.raises(ValidationError):
        HardFilterResult(decision=FilterDecision.REJECT, reasons=[])


def test_match_requires_explanation_not_only_score() -> None:
    with pytest.raises(ValidationError):
        MatchResult(overall=0.86, decision=MatchDecision.STRONG_MATCH)
```

- [ ] **Step 2: Run and confirm missing job contracts**

Run: `python -m pytest tests/schemas/test_jobs.py -q`
Expected: FAIL with missing `jobs` module.

- [ ] **Step 3: Implement job contracts**

`NormalizedJob` contains the approved job fields plus a non-empty list of provenance records. `HardFilterResult` requires at least one `FilterReason` for `REJECT`. `MatchResult` bounds scores to `[0, 1]` and requires at least one strength, partial match, hard gap, or uncertainty so a bare score is invalid. Candidate-job match types must not import optimizer compatibility types.

- [ ] **Step 4: Run job tests**

Run: `python -m pytest tests/schemas/test_jobs.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit job contracts**

```bash
git add src/jobagent/schemas/jobs.py src/jobagent/schemas/__init__.py tests/schemas/test_jobs.py
git commit -m "feat: define explainable job contracts"
```

### Task 5: Resume Optimizer Contracts

**Files:**
- Create: `src/jobagent/schemas/optimizer.py`
- Modify: `src/jobagent/schemas/__init__.py`
- Test: `tests/schemas/test_optimizer.py`

**Interfaces:**
- Consumes: evidence IDs, normalized job IDs, shared contract primitives.
- Produces: optimization plan, resume variant, claim ledger, verification, diff, keyword coverage, and resume compatibility schemas.

- [ ] **Step 1: Write failing grounding tests**

```python
import pytest
from pydantic import ValidationError

from jobagent.schemas.optimizer import ClaimRecord, VerificationStatus


def test_substantive_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ClaimRecord(
            claim_id="CLAIM_001",
            resume_item_id="ITEM_001",
            text="Built a production RAG platform.",
            claim_type="experience",
            evidence_ids=[],
            requirement_ids=["REQ_001"],
            verification_status=VerificationStatus.UNSUPPORTED,
        )


def test_supported_claim_accepts_evidence() -> None:
    claim = ClaimRecord(
        claim_id="CLAIM_002",
        resume_item_id="ITEM_002",
        text="Reduced review time by 30%.",
        claim_type="achievement",
        evidence_ids=["EVID_001"],
        requirement_ids=["REQ_002"],
        verification_status=VerificationStatus.SUPPORTED,
    )
    assert claim.evidence_ids == ["EVID_001"]
```

- [ ] **Step 2: Run and confirm missing optimizer contracts**

Run: `python -m pytest tests/schemas/test_optimizer.py -q`
Expected: FAIL with missing `optimizer` module.

- [ ] **Step 3: Implement optimizer contracts**

Implement the models named in the optimizer design. `ClaimRecord.evidence_ids` is non-empty for every claim. `VerificationReport.passed` can be true only when unsupported, contradicted, unsupported-metric, and semantic-exaggeration counts are zero and evidence coverage is `1.0`. `ResumeCompatibilityResult` is a distinct model from `MatchResult`, with configurable threshold values included in the result rather than imported constants.

- [ ] **Step 4: Run optimizer tests**

Run: `python -m pytest tests/schemas/test_optimizer.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit optimizer contracts**

```bash
git add src/jobagent/schemas/optimizer.py src/jobagent/schemas/__init__.py tests/schemas/test_optimizer.py
git commit -m "feat: define evidence-grounded optimizer contracts"
```

### Task 6: Application Approval and Audit Contracts

**Files:**
- Create: `src/jobagent/schemas/applications.py`
- Modify: `src/jobagent/schemas/__init__.py`
- Test: `tests/schemas/test_applications.py`

**Interfaces:**
- Consumes: job, resume variant, match, diff, and digest identifiers.
- Produces: immutable preview packages, digest-bound approvals, delivery requests/results, batch records, and audits.

- [ ] **Step 1: Write failing approval tests**

```python
from datetime import datetime, timezone

from jobagent.schemas.applications import ApprovalRecord


def test_approval_binds_every_reviewed_artifact() -> None:
    approval = ApprovalRecord(
        application_id="APP_001",
        job_digest="sha256:job",
        resume_digest="sha256:resume",
        message_digest="sha256:message",
        policy_digest="sha256:policy",
        approved_at=datetime.now(timezone.utc),
        approved_by="human",
    )
    assert approval.resume_digest == "sha256:resume"


def test_changed_resume_invalidates_approval() -> None:
    approval = ApprovalRecord(
        application_id="APP_001",
        job_digest="sha256:job",
        resume_digest="sha256:v1",
        message_digest="sha256:message",
        policy_digest="sha256:policy",
        approved_at=datetime.now(timezone.utc),
        approved_by="human",
    )
    assert not approval.matches(
        job_digest="sha256:job",
        resume_digest="sha256:v2",
        message_digest="sha256:message",
        policy_digest="sha256:policy",
    )
```

- [ ] **Step 2: Run and confirm missing application contracts**

Run: `python -m pytest tests/schemas/test_applications.py -q`
Expected: FAIL with missing `applications` module.

- [ ] **Step 3: Implement approval and audit contracts**

`ApprovalRecord` is frozen and exposes the exact keyword-only `matches(...) -> bool` method used above. Separate enums represent application status, send result, and intervention reasons. `ApplicationAudit` records artifact IDs and digests rather than duplicating private bodies. Batch schemas preserve an ordered list and declare sequential execution mode.

- [ ] **Step 4: Run application tests**

Run: `python -m pytest tests/schemas/test_applications.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit application contracts**

```bash
git add src/jobagent/schemas/applications.py src/jobagent/schemas/__init__.py tests/schemas/test_applications.py
git commit -m "feat: define digest-bound approval contracts"
```

### Task 7: Capability and Provider Ports

**Files:**
- Create: `src/jobagent/capabilities.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Consumes: domain contracts and `ContractModel`.
- Produces: `Capability[InputT, OutputT]`, `JobSource`, and `ReasoningProvider` protocols without implementation side effects.

- [ ] **Step 1: Write failing runtime-checkable protocol tests**

```python
from jobagent.capabilities import Capability
from jobagent.schemas.common import ContractModel


class Input(ContractModel):
    value: int


class Output(ContractModel):
    value: int


class Double:
    name = "test.double"

    def __call__(self, data: Input) -> Output:
        return Output(value=data.value * 2)


def test_atomic_capability_has_no_hidden_orchestration() -> None:
    capability: Capability[Input, Output] = Double()
    assert capability(Input(value=2)).value == 4
```

- [ ] **Step 2: Run and confirm missing capability port**

Run: `python -m pytest tests/test_capabilities.py -q`
Expected: FAIL with missing `capabilities` module.

- [ ] **Step 3: Implement protocols**

Define covariant/contravariant generic types for `Capability`. `JobSource` exposes distinct search, fetch, recruiter, preview, and submit methods. `ReasoningProvider.generate` accepts `prompt_id`, a read-only mapping context, and `type[OutputT]`, returning `OutputT`. Protocols contain no concrete provider imports.

- [ ] **Step 4: Run port tests and type checking**

Run: `python -m pytest tests/test_capabilities.py -q`
Expected: `1 passed`.

Run: `python -m mypy src`
Expected: success with no issues.

- [ ] **Step 5: Commit ports**

```bash
git add src/jobagent/capabilities.py tests/test_capabilities.py
git commit -m "feat: add atomic capability provider ports"
```

### Task 8: Progressive Skill Context

**Files:**
- Create: `skills/job-hunting/SKILL.md`
- Create: `skills/job-hunting/agents/openai.yaml`
- Create: `skills/job-hunting/references/product-spec.md`
- Create: `skills/job-hunting/references/architecture-invariants.md`
- Create: `skills/job-hunting/references/capability-catalog.md`
- Create: `skills/job-hunting/references/candidate-kb.md`
- Create: `skills/job-hunting/references/evidence-policy.md`
- Create: `skills/job-hunting/references/job-intelligence.md`
- Create: `skills/job-hunting/references/resume-grounding.md`
- Create: `skills/job-hunting/references/hitl-approval.md`
- Create: `skills/job-hunting/references/connector-contract.md`
- Create: `skills/job-hunting/references/optimizer/workflow.md`
- Create: `skills/job-hunting/references/optimizer/evidence-contract.md`
- Create: `skills/job-hunting/references/optimizer/prompt-routing.md`
- Create: `skills/job-hunting/references/optimizer/quality-gates.md`
- Create: `skills/job-hunting/references/optimizer/failure-handling.md`
- Create: `skills/job-hunting/references/oss/source-manifest.yaml`
- Create: `skills/job-hunting/references/oss/agentmesh-jobagent.md`
- Create: `skills/job-hunting/references/oss/open-boss.md`
- Create: `skills/job-hunting/references/oss/auto-jobhunter.md`
- Test: `tests/test_skill_context.py`

**Interfaces:**
- Consumes: approved design specs and verified OSS license decisions.
- Produces: implicitly discoverable `$job-hunting` workflow with focused on-demand references.

- [ ] **Step 1: Write failing routing tests**

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "job-hunting"


def test_skill_entrypoint_routes_every_sensitive_mode() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for reference in (
        "references/evidence-policy.md",
        "references/hitl-approval.md",
        "references/optimizer/quality-gates.md",
        "references/connector-contract.md",
        "references/oss/source-manifest.yaml",
    ):
        assert reference in text


def test_reference_only_source_is_explicit() -> None:
    text = (SKILL / "references/oss/source-manifest.yaml").read_text(encoding="utf-8")
    assert "Auto-JobHunter" in text
    assert "reference-only" in text
    assert "non-commercial" in text
```

- [ ] **Step 2: Run and confirm missing skill files**

Run: `python -m pytest tests/test_skill_context.py -q`
Expected: FAIL because `SKILL.md` is absent.

- [ ] **Step 3: Create the skill and focused references**

`SKILL.md` frontmatter uses `name: job-hunting` and a discriminating description covering candidate onboarding, job intelligence, evidence-grounded resume optimization, approval review, and connector workflows. Its body contains the four hard safety rules and a routing table. It links references instead of duplicating their detailed content.

`source-manifest.yaml` records the three repositories, verification date `2026-08-21`, license, reuse mode, allowed material, attribution requirement, prohibited use, and risk. Auto-JobHunter is exactly `reference-only` and marked `non-commercial`.

- [ ] **Step 4: Validate the skill and run tests**

Run: `python C:\Users\18121\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/job-hunting`
Expected: validation success.

Run: `python -m pytest tests/test_skill_context.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit Skill Context**

```bash
git add skills/job-hunting tests/test_skill_context.py
git commit -m "feat: add progressive job hunting skill context"
```

### Task 9: Public Architecture, Domain, and OSS Documentation

**Files:**
- Create: `docs/architecture.md`
- Create: `docs/domain-model.md`
- Create: `docs/oss-review.md`
- Test: `tests/test_documentation_contract.py`

**Interfaces:**
- Consumes: implemented schemas, ports, and Skill Context.
- Produces: public documentation matching actual phase-1 file and type names.

- [ ] **Step 1: Write failing documentation tests**

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_architecture_documents_invariants() -> None:
    text = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    assert "CandidateProfile != Resume" in text
    assert "Approval != Send" in text
    assert "CAPTCHA != Retry" in text


def test_oss_review_records_all_sources() -> None:
    text = (ROOT / "docs/oss-review.md").read_text(encoding="utf-8")
    for project in ("AgentMesh-JobAgent", "open-boss", "Auto-JobHunter"):
        assert project in text
```

- [ ] **Step 2: Run and confirm documentation files are missing**

Run: `python -m pytest tests/test_documentation_contract.py -q`
Expected: FAIL because public documents are absent.

- [ ] **Step 3: Write documents from implemented contracts**

`architecture.md` documents dependency direction, capability separation, safety stop states, and the offline mock-first vertical flow. `domain-model.md` documents entity ownership, identifiers, evidence-to-claim relationships, match-versus-compatibility, and approval digest lifecycle. `oss-review.md` records license, intended reuse mode, attribution, risk, and the decision that Auto-JobHunter remains architecture reference only.

- [ ] **Step 4: Run documentation tests**

Run: `python -m pytest tests/test_documentation_contract.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit public documentation**

```bash
git add docs/architecture.md docs/domain-model.md docs/oss-review.md tests/test_documentation_contract.py
git commit -m "docs: publish architecture domain and OSS review"
```

### Task 10: Foundation Quality Gate

**Files:**
- Modify only files identified by failing verification.

**Interfaces:**
- Consumes: all tasks in this plan.
- Produces: installable, lint-clean, type-clean, fully tested foundation release candidate.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Run lint and formatting checks**

Run: `python -m ruff check .`
Expected: no diagnostics.

Run: `python -m ruff format --check .`
Expected: all files already formatted.

- [ ] **Step 3: Run strict type checking**

Run: `python -m mypy src`
Expected: success with no issues.

- [ ] **Step 4: Revalidate Skill Context and privacy state**

Run: `python C:\Users\18121\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/job-hunting`
Expected: validation success.

Run: `git status --short --ignored`
Expected: no private runtime artifact is tracked; expected cache and environment patterns show as ignored if present.

- [ ] **Step 5: Commit verification-only corrections if needed**

```bash
git add pyproject.toml src tests skills docs README.md .gitignore .env.example LICENSE
git commit -m "test: complete foundation quality gate"
```

If verification required no corrections, do not create an empty commit.

## Plan Self-review Result

- Foundation spec coverage: package bootstrap, privacy, schemas, ports, Skill Context, public architecture, domain model, and OSS review are included.
- Deferred by design: SQLite, candidate services, mock connector, reasoning implementation, runtime optimizer prompts, application mutation, CLI commands, and real connectors each require a later independent plan.
- Type consistency: `ContractModel`, evidence IDs, `MatchResult`, `ResumeCompatibilityResult`, and `ApprovalRecord.matches` names are stable across tasks.
- Safety consistency: no task combines search and delivery, approval and send, candidate match and resume compatibility, or CAPTCHA and retry.
