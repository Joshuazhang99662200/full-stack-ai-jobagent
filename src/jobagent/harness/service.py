"""Track one workflow without performing candidate confirmation or delivery."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from jobagent.errors import ContractValidationError
from jobagent.harness.runtime import runtime_fingerprint
from jobagent.schemas.applications import ApplicationPackage
from jobagent.schemas.candidate import CandidateDraft
from jobagent.schemas.common import ContractModel
from jobagent.schemas.harness import HarnessRun, Host, PdfCheckReport, RunArtifact, RunPhase
from jobagent.schemas.jobs import JobRequirementProfile
from jobagent.schemas.optimizer import (
    BaseResumeDocument,
    ClaimReviewSet,
    ResumeVariant,
    TailoredDraft,
)
from jobagent.schemas.reasoning import ReasoningHandoffRequest
from jobagent.storage.harness_store import HarnessStore

ARTIFACT_CONTRACTS: dict[str, type[ContractModel]] = {
    model.__name__: model
    for model in (
        CandidateDraft,
        JobRequirementProfile,
        BaseResumeDocument,
        ResumeVariant,
        ReasoningHandoffRequest,
        ApplicationPackage,
        PdfCheckReport,
        TailoredDraft,
        ClaimReviewSet,
    )
}
TERMINAL = {RunPhase.COMPLETED, RunPhase.CANCELLED, RunPhase.FAILED}


class HarnessService:
    def __init__(
        self,
        workspace: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = 1800,
        runtime_digest: str | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.store = HarnessStore(self.workspace)
        self.clock = clock or (lambda: datetime.now(UTC))
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.lease_seconds = lease_seconds
        self.runtime_digest = runtime_digest or runtime_fingerprint()

    def start(self, candidate_id: str, host: str, session_id: str) -> HarnessRun:
        now = self.clock()
        run = HarnessRun(
            run_id="RUN_" + uuid4().hex.upper(),
            candidate_id=candidate_id,
            runtime_digest=self.runtime_digest,
            host=cast(Host, host),
            session_id=session_id,
            created_at=now,
            updated_at=now,
            lease_until=now + timedelta(seconds=self.lease_seconds),
        )
        self.store.directory(run.run_id).mkdir(parents=True, exist_ok=False)
        with self.store.lock(run.run_id):
            self.store.write(run)
        return run

    def status(self, run_id: str) -> HarnessRun:
        return self.store.read(run_id)

    def _owned(self, run: HarnessRun, session_id: str) -> None:
        if run.runtime_digest != self.runtime_digest:
            raise ContractValidationError(
                "Run runtime changed; use the matching release or migrate."
            )
        if run.session_id != session_id or run.lease_until is None:
            raise ContractValidationError("Run lease belongs to another session.")
        if run.lease_until <= self.clock():
            raise ContractValidationError("Run lease expired; explicitly recover with resume.")

    def _artifact(self, path: Path, contract: str) -> RunArtifact:
        path = path.resolve()
        if not path.is_relative_to(self.workspace):
            raise ContractValidationError("Artifact must remain inside the workspace.")
        model = ARTIFACT_CONTRACTS.get(contract)
        if model is None:
            raise ContractValidationError("Unsupported artifact contract.")
        try:
            content = path.read_bytes()
            model.model_validate_json(content)
        except (OSError, ValueError) as error:
            raise ContractValidationError("Artifact violates its contract.") from error
        return RunArtifact(
            path=path.relative_to(self.workspace).as_posix(),
            contract=contract,
            digest="sha256:" + hashlib.sha256(content).hexdigest(),
        )

    def resume(
        self,
        run_id: str,
        host: str,
        session_id: str,
        *,
        recover: bool = False,
    ) -> HarnessRun:
        if not session_id:
            raise ContractValidationError("A session identifier is required.")
        with self.store.lock(run_id):
            run = self.store.read(run_id)
            if run.runtime_digest != self.runtime_digest:
                raise ContractValidationError(
                    "Run runtime changed; use the matching release or migrate."
                )
            if run.phase in TERMINAL:
                raise ContractValidationError("Cannot resume a terminal run; start a new run.")
            if run.session_id is not None:
                if run.lease_until is None or run.lease_until <= self.clock():
                    if not recover:
                        raise ContractValidationError("Expired lease requires explicit recover.")
                elif run.session_id != session_id or run.host != host:
                    raise ContractValidationError(
                        "Active run lease belongs to another host/session."
                    )
            for saved in run.artifacts:
                try:
                    current = self._artifact(self.workspace / saved.path, saved.contract)
                except ContractValidationError as error:
                    raise ContractValidationError(
                        "Saved artifact changed or disappeared."
                    ) from error
                if current != saved:
                    raise ContractValidationError("Saved artifact changed; review before resuming.")
            run.host = cast(Host, host)
            run.session_id = session_id
            run.updated_at = self.clock()
            run.lease_until = self.clock() + timedelta(seconds=self.lease_seconds)
            self.store.write(run)
            return run

    def checkpoint(
        self,
        run_id: str,
        session_id: str,
        phase: RunPhase,
        artifact: Path | None = None,
        contract: str | None = None,
    ) -> HarnessRun:
        with self.store.lock(run_id):
            run = self.store.read(run_id)
            self._owned(run, session_id)
            if run.phase in TERMINAL:
                raise ContractValidationError("Cannot change a terminal run.")
            if (artifact is None) != (contract is None):
                raise ContractValidationError(
                    "Artifact path and contract must be supplied together."
                )
            if artifact is not None and contract is not None:
                saved = self._artifact(artifact, contract)
                run.artifacts = [a for a in run.artifacts if a.path != saved.path] + [saved]
            run.phase = phase
            run.updated_at = self.clock()
            run.lease_until = self.clock() + timedelta(seconds=self.lease_seconds)
            self.store.write(run)
            return run

    def release(self, run_id: str, session_id: str) -> HarnessRun:
        with self.store.lock(run_id):
            run = self.store.read(run_id)
            self._owned(run, session_id)
            run.session_id = None
            run.lease_until = None
            run.updated_at = self.clock()
            self.store.write(run)
            return run
