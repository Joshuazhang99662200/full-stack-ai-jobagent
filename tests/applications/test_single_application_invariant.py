"""Structural guards for `Search != Apply`, `Approval != Send` and no bulk delivery."""

import ast
import inspect
import pkgutil
from collections.abc import Iterator
from pathlib import Path
from typing import get_type_hints

import pytest

import jobagent.applications
from jobagent.applications import ports
from jobagent.cli import applications as applications_cli

PACKAGE_ROOT = Path(inspect.getfile(jobagent.applications)).parent
CLI_MODULE = Path(inspect.getfile(applications_cli))
SOURCE_FILES = [*sorted(PACKAGE_ROOT.glob("*.py")), CLI_MODULE]

BULK_TYPES = (
    "ApplicationPackage",
    "DeliveryRequest",
    "ApprovalRecord",
    "ApplicationAudit",
)
CONTAINER_PREFIXES = ("list", "List", "Sequence", "tuple", "Tuple", "set", "Iterable", "Iterator")


def module_names() -> list[str]:
    return [
        f"jobagent.applications.{info.name}"
        for info in pkgutil.iter_modules([str(PACKAGE_ROOT)])
    ]


def annotations() -> Iterator[tuple[str, str, str]]:
    for path in SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            arguments = [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]
            for argument in arguments:
                if argument.annotation is None:
                    continue
                yield path.name, f"{node.name}:{argument.arg}", ast.unparse(argument.annotation)


def test_no_parameter_anywhere_accepts_more_than_one_application() -> None:
    scanned = list(annotations())
    assert any(
        annotation.endswith("ApplicationPackage") for _, _, annotation in scanned
    ), "the scan found no single-application parameters, so it proves nothing"

    offenders = [
        (module, parameter, annotation)
        for module, parameter, annotation in scanned
        if annotation.startswith(CONTAINER_PREFIXES)
        and any(bulk in annotation for bulk in BULK_TYPES)
    ]

    assert offenders == []


def test_delivery_module_never_loops() -> None:
    tree = ast.parse((PACKAGE_ROOT / "delivery.py").read_text(encoding="utf-8"))
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.For | ast.While)]
    comprehensions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp)
    ]

    assert loops == []
    assert comprehensions == []


def test_batch_contracts_are_not_reachable_from_the_delivery_chain() -> None:
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "BatchApplication" not in text, path.name
        assert "BatchId" not in text, path.name


@pytest.mark.parametrize("name", module_names())
def test_domain_modules_stay_free_of_typer_sqlite_and_platform_sdks(name: str) -> None:
    module = __import__(name, fromlist=["*"])
    source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    for forbidden in ("import typer", "import sqlite3", "selenium", "playwright", "requests"):
        assert forbidden not in source, (name, forbidden)


def test_delivery_port_exposes_exactly_one_single_application_operation() -> None:
    hints = get_type_hints(ports.ApplicationDeliverySource.submit_application)

    assert hints["package"].__name__ == "ApplicationPackage"
    assert hints["return"].__name__ == "DeliveryResult"
    operations = {
        name
        for name in vars(ports.ApplicationDeliverySource)
        if not name.startswith("_") and callable(getattr(ports.ApplicationDeliverySource, name))
    }
    assert operations == {"submit_application"}


def test_no_real_platform_connector_ships_with_the_delivery_package() -> None:
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8").casefold()
        for platform in ("liepin", "boss", "zhilian", "linkedin", "51job", "lagou"):
            assert platform not in text, (path.name, platform)
