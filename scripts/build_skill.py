"""Build an isolated, integrity-checked Agent Skill; no host configuration writes."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("codex", "claude-code")


def build_skill(destination: Path, host: str) -> Path:
    if host not in HOSTS:
        raise ValueError(f"Unsupported host: {host}")
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    sources: list[tuple[Path, Path]] = []
    for source_root, relative_root, extensions in (
        (ROOT / "skills/job-hunting", Path("."), {".md", ".yaml", ".json", ".py"}),
        (ROOT / "src/jobagent", Path("runtime/src/jobagent"), {".py", ".sql", ".json"}),
    ):
        for path in sorted(source_root.rglob("*")):
            relative = path.relative_to(source_root)
            if any(
                part in {".jobagent", "private", "variants", ".venv", "__pycache__"}
                for part in relative.parts
            ):
                continue
            if relative_root == Path(".") and relative.parts[0] not in {
                "SKILL.md",
                "references",
                "optimizer",
                "scripts",
                "agents",
                "assets",
                "sources",
            }:
                continue
            if path.is_symlink():
                raise ValueError(f"Symlinks cannot be distributed: {path}")
            if path.is_file() and (path.suffix in extensions or path.name == "py.typed"):
                sources.append((path, relative_root / path.relative_to(source_root)))
    sources.append((ROOT / "LICENSE", Path("LICENSE")))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    revision = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    )
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for source, relative in sources:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {
        "format_version": 1,
        "name": "job-hunting",
        "host": host,
        "version": project["version"],
        "source_revision": revision,
        "source_dirty": dirty,
        "dependencies": project["dependencies"],
        "files": hashes,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="构建独立求职 skill,不覆盖已有安装。")
    parser.add_argument("--host", choices=HOSTS, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    skill = build_skill(args.destination, args.host)
    if args.archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.archive, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(skill.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(
                        (Path("job-hunting") / path.relative_to(skill)).as_posix()
                    )
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, path.read_bytes())
    print(json.dumps({"skill": str(skill), "archive": str(args.archive) if args.archive else None}))


if __name__ == "__main__":
    main()
