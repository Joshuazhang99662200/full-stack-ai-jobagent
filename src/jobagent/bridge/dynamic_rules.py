"""Read an explicit private snapshot; malformed or stale contents never fall back."""

import sqlite3
from pathlib import Path

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet


def load_rule_snapshot(path: Path, candidate_id: str | None = None) -> DynamicRuleSet:
    resolved = path.expanduser().resolve()
    parts = [part.casefold() for part in resolved.parts]
    if ".jobagent" not in parts and not any(
        parts[i : i + 2] == ["candidate", "private"] for i in range(len(parts) - 1)
    ):
        raise ContractValidationError("Dynamic settings must stay in a private workspace.")
    try:
        snapshot = validate_snapshot(DynamicRuleSet.model_validate_json(resolved.read_bytes()))
    except (OSError, ValidationError) as error:
        raise ContractValidationError("Cannot read a valid dynamic-rule snapshot.") from error
    if candidate_id is not None and snapshot.candidate_id != candidate_id:
        raise ContractValidationError("Dynamic rule candidate scope mismatch.")
    return snapshot


def load_effective_rule_snapshot(
    path: Path | None,
    candidate_id: str | None,
    database: Path | None,
) -> DynamicRuleSet | None:
    """Active local rules require an explicit current export; no silent legacy fallback."""
    active_version: str | None = None
    active_exists = False
    if database is not None and database.is_file():
        try:
            with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "dynamic_rule_heads" in tables:
                    if candidate_id is None:
                        active_exists = (
                            connection.execute(
                                "SELECT 1 FROM dynamic_rule_heads LIMIT 1"
                            ).fetchone()
                            is not None
                        )
                    else:
                        row = connection.execute(
                            "SELECT version FROM dynamic_rule_heads WHERE candidate_id=?",
                            (candidate_id,),
                        ).fetchone()
                        active_version = row[0] if row else None
                        active_exists = row is not None
        except sqlite3.Error as error:
            raise ContractValidationError("Cannot verify active dynamic rules.") from error
    if path is None:
        if active_exists:
            raise ContractValidationError(
                "Active dynamic rules require an explicit current snapshot."
            )
        return None
    if candidate_id is None:
        raise ContractValidationError("Dynamic rules require an explicit candidate scope.")
    snapshot = load_rule_snapshot(path, candidate_id)
    if active_version is not None and snapshot.version != active_version:
        raise ContractValidationError("Dynamic rule export is stale; read the current version.")
    return snapshot
