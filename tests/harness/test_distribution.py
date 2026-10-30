"""A published skill must run independently of its development checkout."""

import importlib.util
import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def builder():
    spec = importlib.util.spec_from_file_location("build_skill", ROOT / "scripts/build_skill.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_skill


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_standalone_skill_runs_without_checkout(tmp_path, host):
    skill = builder()(tmp_path / "installed" / "job-hunting", host)
    result = subprocess.run(
        [sys.executable, str(skill / "scripts/bootstrap.py"), "--", "optimizer", "capabilities"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["entries"]
    manifest = json.loads((skill / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["host"] == host
    assert not any("candidate/private" in p or ".sqlite" in p for p in manifest["files"])


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_standalone_skill_recognizes_listing_source_without_network(tmp_path, host):
    skill = builder()(tmp_path / "installed" / "job-hunting", host)
    result = subprocess.run(
        [
            sys.executable,
            str(skill / "scripts/bootstrap.py"),
            "--",
            "jobs",
            "search",
            "--source",
            "liepin",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    # A recognized listing source rejects full-JD discovery before any HTTP/CLI call.
    assert result.returncode == 1
    error = json.loads(result.stdout)["error"]
    assert error["details"].get("use_instead") == "jobs listings", error


def test_tampered_runtime_never_executes(tmp_path):
    skill = builder()(tmp_path / "job-hunting", "codex")
    (skill / "runtime/src/jobagent/__init__.py").write_text("raise RuntimeError('EXECUTED')")
    result = subprocess.run(
        [sys.executable, str(skill / "scripts/bootstrap.py"), "--", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "integrity" in result.stdout.lower()
    assert "EXECUTED" not in result.stderr


def test_existing_install_is_not_overwritten(tmp_path):
    target = tmp_path / "job-hunting"
    target.mkdir()
    marker = target / "user-file"
    marker.write_text("keep")
    with pytest.raises(FileExistsError):
        builder()(target, "codex")
    assert marker.read_text() == "keep"


def test_readonly_probe_checks_private_environment_not_global_dependencies(tmp_path):
    skill = builder()(tmp_path / "job-hunting", "codex")
    workspace = tmp_path / "personal"
    version = json.loads((skill / "manifest.json").read_text(encoding="utf-8"))["version"]
    environment = workspace / ".jobagent/runtime" / version
    venv.EnvBuilder(with_pip=False).create(environment)
    result = subprocess.run(
        [
            sys.executable,
            str(skill / "scripts/bootstrap.py"),
            "--workspace",
            str(workspace),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["missing_dependencies"]
    assert not (workspace / ".jobagent/runs").exists()


def test_unknown_host_does_not_write(tmp_path):
    with pytest.raises(ValueError):
        builder()(tmp_path / "skill", "unknown")
    assert not (tmp_path / "skill").exists()


def test_accidental_private_state_inside_skill_tree_is_not_distributed(tmp_path):
    build = builder()
    source = tmp_path / "source"
    skill = source / "skills/job-hunting"
    (skill / ".jobagent/handoff").mkdir(parents=True)
    (skill / "candidate/private").mkdir(parents=True)
    (skill / "references").mkdir()
    (source / "src/jobagent").mkdir(parents=True)
    (source / "LICENSE").write_text("test license")
    (source / "pyproject.toml").write_text('[project]\nversion="test"\ndependencies=[]')
    (source / "src/jobagent/__init__.py").write_text('"""synthetic runtime"""')
    (skill / "SKILL.md").write_text("synthetic skill")
    (skill / "references/policy.md").write_text("policy")
    (skill / ".jobagent/handoff/request.json").write_text('{"private":"synthetic"}')
    (skill / "candidate/private/resume.json").write_text('{"private":"synthetic"}')
    build.__globals__["ROOT"] = source
    installed = build(tmp_path / "installed", "codex")
    assert (installed / "references/policy.md").exists()
    assert not (installed / ".jobagent").exists()
    assert not (installed / "candidate").exists()


def synthetic_release_source(tmp_path):
    build = builder()
    source = tmp_path / "source"
    policy = source / "skills/job-hunting/references/policy.md"
    policy.parent.mkdir(parents=True)
    policy.write_text("Public policy", encoding="utf-8")
    (source / "skills/job-hunting/SKILL.md").write_text("Public skill", encoding="utf-8")
    (source / "src/jobagent").mkdir(parents=True)
    (source / "src/jobagent/__init__.py").write_text('"""Public runtime."""')
    (source / "LICENSE").write_text("test license")
    (source / "pyproject.toml").write_text('[project]\nversion="test"\ndependencies=[]')
    build.__globals__["ROOT"] = source
    return build, source, policy


@pytest.mark.parametrize(
    "leak",
    [
        'api_key = "' + "sk-" + "synthetic" * 4 + '"',
        'refresh_token = "' + "synthetic" * 4 + '"',
        'refreshToken = "synthetic credential with punctuation!"',
        'client_secret = "synthetic credential with punctuation!"',
        'apiKey = "synthetic credential with punctuation!"',
        "C:" + "\\Users\\SYNTHETIC\\candidate\\resume.pdf",
        "/home/SYNTHETIC/candidate/resume.pdf",
        "/home/合成用户/candidate/resume.pdf",
        "-----BEGIN PRIVATE KEY-----\nSYNTHETIC ONLY",
        "candidate@" + "synthetic-do-not-use.org",
    ],
)
def test_release_privacy_rejects_leaks_before_any_output_write(tmp_path, leak):
    build, _, policy = synthetic_release_source(tmp_path)
    policy.write_text(leak, encoding="utf-8")
    target = tmp_path / "installed"

    with pytest.raises(ValueError, match="privacy") as caught:
        build(target, "codex")

    assert not target.exists()
    assert leak not in str(caught.value)
    assert "references/policy.md" in str(caught.value)


def test_release_privacy_allows_documented_placeholders_and_reserved_contacts(tmp_path):
    build, _, policy = synthetic_release_source(tmp_path)
    policy.write_text(
        'api_key = "YOUR_API_KEY"\n'
        'refresh_token = "<provided-by-user>"\n'
        "ada@example.com\nrecruiter@jobs.example.test\n",
        encoding="utf-8",
    )
    result = build(tmp_path / "installed", "codex")
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["privacy_check"]["passed"] is True
    assert manifest["privacy_check"]["rules_version"] == "public-release-v1"


def test_private_directory_names_are_excluded_case_insensitively(tmp_path):
    build, source, _ = synthetic_release_source(tmp_path)
    leak = source / "skills/job-hunting/references/Private/resume.json"
    leak.parent.mkdir()
    leak.write_text('{"contact":"synthetic private content"}')

    result = build(tmp_path / "installed", "codex")

    assert not (result / "references/Private").exists()
