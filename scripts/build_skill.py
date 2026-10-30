"""Build an isolated, integrity-checked Agent Skill; no host configuration writes."""

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("codex", "claude-code")
PRIVACY_RULES_VERSION = "public-release-v1"
_PRIVACY_PATTERNS = {
    "personal_home_path": re.compile(
        r"\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\\/\s\"'<>]+"
        r"|/(?:Users|home)/[^/\s\"'<>]+/", re.IGNORECASE,
    ),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "credential": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
        r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b",
    ),
    "credential_literal": re.compile(
        r"[\"']?(?:access_?token|refresh_?token|app_?secret|client_?secret|api_?key|password)"
        r"[\"']?"
        r"\s*[:=]\s*[\"'](?!YOUR_[A-Z_]+[\"']|<[^>]+>[\"'])"
        r"[^\"'\r\n]{12,}[\"']", re.IGNORECASE,
    ),
    "personal_phone": re.compile(r"(?<!\w)1[3-9]\d{9}(?!\w)"),
}
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def privacy_findings(relative: Path, content: bytes) -> list[dict[str, str | int]]:
    """Return locations and rule names only, never matching private values."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [{"path": relative.as_posix(), "line": 1, "rule": "non_utf8_text"}]
    findings = []
    for rule, pattern in _PRIVACY_PATTERNS.items():
        findings.extend(
            {"path": relative.as_posix(), "line": text.count("\n", 0, match.start()) + 1,
             "rule": rule}
            for match in pattern.finditer(text)
        )
    for match in _EMAIL.finditer(text):
        domain = match.group(1).lower()
        if domain in {"example.com", "example.net", "example.org"} or domain.endswith(
            (".example.com", ".example.net", ".example.org", ".test", ".invalid", ".example")
        ):
            continue
        findings.append({"path": relative.as_posix(),
                         "line": text.count("\n", 0, match.start()) + 1,
                         "rule": "personal_email"})
    return findings


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
                part.casefold() in {
                    ".jobagent", "private", "variants", ".venv", "__pycache__", ".git",
                    "node_modules",
                }
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
    # Inspect the exact bytes that will be copied, before creating any destination.
    contents = [(relative, source.read_bytes()) for source, relative in sources]
    findings = [finding for relative, content in contents
                for finding in privacy_findings(relative, content)]
    if findings:
        raise ValueError("Release privacy check failed: " + json.dumps(findings))
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
    for relative, content in contents:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
    manifest = {
        "format_version": 1,
        "name": "job-hunting",
        "host": host,
        "version": project["version"],
        "source_revision": revision,
        "source_dirty": dirty,
        "dependencies": project["dependencies"],
        "files": hashes,
        "privacy_check": {"passed": True, "rules_version": PRIVACY_RULES_VERSION,
                          "files_checked": len(contents)},
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
