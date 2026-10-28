"""Shared private-file JSON boundaries without source-text error echoes."""

import json
from pathlib import Path
from typing import Never, TypeVar

import typer
from pydantic import ValidationError

from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.common import ContractModel
from jobagent.storage.database import Database

ModelT = TypeVar("ModelT", bound=ContractModel)


def read_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Private input does not satisfy the contract.", details={"contract": model.__name__}
        ) from error


def open_database(path: Path) -> Database:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return database


def fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)
