"""Locate and read the checked-in skill package.

The skill's reference documents are the single source of truth for the rules that
govern reasoning steps. Runtime prompts quote them rather than restating them, so
a policy change lands in exactly one place.
"""

from importlib import resources
from pathlib import Path

from jobagent.errors import ContractValidationError

SKILL_PACKAGE = "job-hunting"


def _packaged_skill_root() -> Path | None:
    try:
        candidate = resources.files("jobagent.optimizer").joinpath("resources", SKILL_PACKAGE)
        if candidate.is_dir():
            return Path(str(candidate))
    except (ModuleNotFoundError, OSError, TypeError):
        pass
    return None


def default_skill_root() -> Path:
    """Resolve the skill root from the installed package, else the source tree."""
    packaged = _packaged_skill_root()
    if packaged is not None:
        return packaged

    module_path = Path(__file__).resolve()
    for ancestor in module_path.parents:
        candidate = ancestor / "skills" / SKILL_PACKAGE
        if candidate.is_dir():
            return candidate
    return module_path.parents[2] / "skills" / SKILL_PACKAGE


def read_reference(relative_path: str, *, root: Path | None = None) -> str:
    """Read one skill reference document verbatim."""
    skill_root = root or default_skill_root()
    path = skill_root / relative_path
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ContractValidationError(
            "A required skill reference document is missing.",
            details={"relative_path": relative_path, "skill_root": str(skill_root)},
        ) from error
