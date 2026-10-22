"""Portable launcher. Check integrity before importing any bundled runtime code."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def manifest() -> dict:
    data = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if data["format_version"] != 1 or data["host"] not in ("codex", "claude-code"):
        raise ValueError("Unsupported manifest")
    for relative, digest in data["files"].items():
        path = ROOT / relative
        if ROOT not in path.resolve().parents or path.is_symlink():
            raise ValueError("Invalid manifest path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"integrity mismatch: {relative}")
    listed = set(data["files"])
    for path in (ROOT / "runtime").rglob("*"):
        if (
            path.is_file()
            and path.suffix in {".py", ".sql", ".json"}
            and path.relative_to(ROOT).as_posix() not in listed
        ):
            raise ValueError("Unlisted executable runtime file")
    return data


def dependencies(requirements: list[str]) -> list[str]:
    missing = []
    for requirement in requirements:
        name, constraints = re.split(r"(?=[<>=])", requirement, maxsplit=1)
        try:
            actual = tuple(int(p) for p in importlib.metadata.version(name).split(".")[:3])
        except (importlib.metadata.PackageNotFoundError, ValueError):
            missing.append(requirement)
            continue
        for constraint in constraints.split(","):
            match = re.fullmatch(r"(>=|<)([\d.]+)", constraint.strip())
            if not match:
                raise ValueError("Unsupported dependency constraint")
            bound = tuple(int(p) for p in match[2].split("."))
            width = max(len(actual), len(bound))
            padded_actual = actual + (0,) * (width - len(actual))
            padded_bound = bound + (0,) * (width - len(bound))
            if (match[1] == ">=" and padded_actual < padded_bound) or (
                match[1] == "<" and padded_actual >= padded_bound
            ):
                missing.append(requirement)
                break
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="求职 harness 启动器;首次调用先 --check。")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if sys.version_info < (3, 11):  # noqa: UP036 -- launcher also runs before project installation
        print(json.dumps({"error": "Python 3.11+ required"}))
        return 1
    try:
        data = manifest()
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"error": "integrity check failed", "detail": str(error)}))
        return 1
    workspace = args.workspace.resolve()
    if workspace == ROOT or ROOT in workspace.parents:
        print(json.dumps({"error": "Choose a writable workspace outside the installed skill"}))
        return 1
    environment = workspace / ".jobagent/runtime" / data["version"]
    if not environment.resolve().is_relative_to(workspace):
        print(json.dumps({"error": "Private environment escapes the workspace"}))
        return 1
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if python.exists() and Path(sys.prefix).resolve() != environment.resolve() and not args.setup:
        return subprocess.run(
            [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
            check=False,
        ).returncode
    missing = dependencies(data["dependencies"])
    if args.check:
        print(
            json.dumps(
                {
                    "integrity": "ok",
                    "host": data["host"],
                    "version": data["version"],
                    "python": sys.version.split()[0],
                    "missing_dependencies": missing,
                    "private_environment": str(python) if python.exists() else None,
                    "browser": "host_probe_required",
                    "scheduler": "host_probe_required",
                    "renderer": "host_probe_required",
                    "workspace": str(workspace),
                }
            )
        )
        return 0
    if args.setup:
        workspace.mkdir(parents=True, exist_ok=True)
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        return subprocess.run(
            [str(python), "-m", "pip", "install", *data["dependencies"]],
            check=False,
        ).returncode
    if missing:
        print(
            json.dumps(
                {"error": "dependencies missing; invoke --setup explicitly", "missing": missing}
            )
        )
        return 1
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.print_help()
        return 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "runtime/src")
    env["JOBAGENT_SKILL_ROOT"] = str(ROOT)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [str(python) if python.exists() else sys.executable, "-m", "jobagent.cli.app", *command],
        cwd=workspace,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
