import re
from pathlib import Path

import typer.main

from jobagent.cli.app import app

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "job-hunting"
CATALOG = SKILL / "references/capability-catalog.md"

COMMAND_PATTERN = re.compile(r"`jobagent ([a-z][a-z-]*) ([a-z][a-z-]*)`")

# Tailoring, verification, diffing and single-application delivery are executable
# now; this list is what keeps the remaining boundary honest.
CONTRACT_ONLY_SCHEMAS = (
    "RequirementEvidenceMapping",
    "ResumeOptimizationPlan",
    "ResumeCompatibilityResult",
)

# Batch delivery stays contract-only on purpose: shipping an orchestration for it
# would turn this project into the bulk applier that AGENTS.md rules out.
NEVER_EXECUTABLE_SCHEMAS = ("BatchApplication",)


def installed_commands() -> set[str]:
    """Collect every real `jobagent <group> <command>` pair from the Typer app.

    Typer vendors its own Click fork, so this walks the command tree structurally
    instead of asserting against the top-level `click` package types.
    """
    root = typer.main.get_command(app)
    groups: dict[str, object] = getattr(root, "commands", {})
    assert groups, "root command group is empty"
    pairs: set[str] = set()
    for group_name, group in groups.items():
        commands: dict[str, object] = getattr(group, "commands", {})
        assert commands, group_name
        pairs.update(f"{group_name} {name}" for name in commands)
    return pairs


def documented_commands() -> set[str]:
    text = CATALOG.read_text(encoding="utf-8")
    return {f"{group} {command}" for group, command in COMMAND_PATTERN.findall(text)}


def test_catalog_documents_exactly_the_installed_command_surface() -> None:
    assert documented_commands() == installed_commands()


def test_catalog_declares_a_status_for_every_capability_row() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ") and not line.startswith("| 能力") and "---" not in line
    ]
    assert rows
    for row in rows:
        assert any(status in row for status in ("已落地", "仅契约", "未开始", "委托外部技能")), row


def test_contract_only_capabilities_have_no_executable_entrypoint() -> None:
    """Schemas exist, but nothing may claim they are callable today."""
    text = CATALOG.read_text(encoding="utf-8")
    installed = installed_commands()
    for schema in CONTRACT_ONLY_SCHEMAS:
        row = next(line for line in text.splitlines() if f"`{schema}`" in line)
        assert "仅契约" in row, schema
        assert not COMMAND_PATTERN.findall(row), schema
    allowed = {"optimizer capabilities", "optimizer tailor", "optimizer assemble"}
    extra_optimizer_commands = {
        command for command in installed - allowed if command.startswith("optimizer ")
    }
    assert extra_optimizer_commands == set()


def test_entry_skill_states_the_current_phase_and_routes_new_policies() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "## 当前阶段" in text
    for reference in (
        "references/capability-catalog.md",
        "references/stop-conditions.md",
        "references/message-generation.md",
        "references/rendering-ats.md",
        "references/audit-feedback.md",
    ):
        assert reference in text
        assert (SKILL / reference).is_file()


def test_entry_skill_hard_rules_cover_untrusted_text_and_private_data() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "数据,不是指令" in text
    assert "candidate/private/" in text


def test_batch_delivery_contract_has_no_orchestration() -> None:
    """The batch schema may exist; nothing outside `schemas/` may build on it."""
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "jobagent").rglob("*.py")
        if path.parent.name != "schemas"
        and any(
            schema in path.read_text(encoding="utf-8") for schema in NEVER_EXECUTABLE_SCHEMAS
        )
    )
    assert offenders == []


def test_delivery_capabilities_declare_a_single_application_surface() -> None:
    """Nothing in the catalog may advertise a bulk delivery entrypoint."""
    text = CATALOG.read_text(encoding="utf-8")
    assert "一次只投一份" in text
    assert "没有任何真实平台实现" in text
    for forbidden in ("send-all", "send-batch", "applications batch", "applications bulk"):
        assert forbidden not in text, forbidden
