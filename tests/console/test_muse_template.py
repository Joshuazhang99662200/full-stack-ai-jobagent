import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_muse_transport_generated_from_authoritative_schemas():
    result = subprocess.run(
        [sys.executable, "scripts/build_muse_contracts.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_muse_reference_layout_is_preserved_and_personal_migrations_are_absent():
    source = (ROOT / "frontend/src/muse/MuseApp.tsx").read_text(encoding="utf-8")
    for name in [
        "FiveColumnTable",
        "TodoDialog",
        "JobDetailDialog",
        "ExecConfirmView",
        "EchoPanel",
        "MaterialList",
        "RunsPanel",
        "CommsPanel",
        "AboutPanel",
    ]:
        assert f"function {name}(" in source
    assert "需要你决定" not in source
    assert "Signal / Harness" not in source
    assert 'j.job["host_rank"]) >= 160' not in source
    assert "@hatch/space-sdk" not in source
    assert "./console/console.js" not in source


def test_zip_classes_and_theme_keep_the_recorded_source_fingerprints():
    directory = ROOT / "frontend/src/muse"
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    source = (directory / "MuseApp.tsx").read_text(encoding="utf-8")
    classes = re.findall(r'className="([^"]*)"', source)
    assert len(classes) == provenance["zip_literal_classes"]
    digest = hashlib.sha256("\n".join(classes).encode()).hexdigest()
    assert digest == provenance["zip_literal_classes_sha256"]
    assert (
        hashlib.sha256((directory / "theme.css").read_bytes()).hexdigest()
        == provenance["zip_theme_sha256"]
    )


def test_current_muse_style_declarations_keep_the_live_reference_values():
    directory = ROOT / "frontend/src/muse"
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    css = (directory / "current.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    declarations = re.findall(r"(?<=[{;])\s*([-\w]+)\s*:\s*([^;{}]+)", css)
    original = [
        (key, re.sub(r"\s+", " ", value.strip()))
        for key, value in declarations[: provenance["current_style_declarations"]]
    ]
    encoded = json.dumps(original, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == provenance["current_declarations_sha256"]
