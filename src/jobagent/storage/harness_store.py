"""Exclusive mutations and atomic state writes in a private workspace."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from jobagent.errors import ContractValidationError
from jobagent.schemas.harness import HarnessRun


class HarnessStore:
    def __init__(self, workspace: Path) -> None:
        self.root = workspace.resolve() / ".jobagent/runs"

    def directory(self, run_id: str) -> Path:
        import re

        if not re.fullmatch(r"RUN_[A-F0-9]{32}", run_id):
            raise ContractValidationError("Invalid run identifier.")
        path = self.root / run_id
        if path.resolve() != path or self.root.resolve() != self.root:
            raise ContractValidationError("Run directory escapes the workspace.")
        return path

    def read(self, run_id: str) -> HarnessRun:
        try:
            run = HarnessRun.model_validate_json(
                (self.directory(run_id) / "state.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise ContractValidationError("Run state is missing or invalid.") from error
        if run.run_id != run_id:
            raise ContractValidationError("Run state identity mismatch.")
        return run

    @contextmanager
    def lock(self, run_id: str) -> Iterator[None]:
        directory = self.directory(run_id)
        path = directory / "state.lock"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise ContractValidationError("Run state is locked; investigate the owner.") from error
        except OSError as error:
            raise ContractValidationError("Run directory is unavailable.") from error
        try:
            os.close(descriptor)
            yield
        finally:
            path.unlink()

    def write(self, run: HarnessRun) -> None:
        directory = self.directory(run.run_id)
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, directory / "state.json")
        finally:
            temporary.unlink(missing_ok=True)
