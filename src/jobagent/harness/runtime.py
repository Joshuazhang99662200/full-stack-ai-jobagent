"""Fingerprint code and policy, excluding host labels and user state."""

import hashlib
from pathlib import Path

from jobagent.optimizer.review import content_digest
from jobagent.skill_resources import default_skill_root


def runtime_fingerprint() -> str:
    files = {}
    for label, root, extensions in (
        ("code", Path(__file__).resolve().parents[1], {".py", ".sql", ".json"}),
        ("skill", default_skill_root(), {".md", ".yaml", ".json", ".py"}),
    ):
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(p in {"runtime", ".jobagent", "__pycache__"} for p in relative.parts):
                continue
            if path.name == "manifest.json" or not path.is_file() or path.suffix not in extensions:
                continue
            files[f"{label}/{relative.as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return content_digest(files)
