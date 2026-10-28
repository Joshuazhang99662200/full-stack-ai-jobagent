# ruff: noqa: RUF001 -- Chinese Markdown format is intentional.
"""Parse and render private Markdown policies; never performs file I/O."""

import json

import yaml
from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.schemas.lexicon import Lexicon

DIMENSIONS = ("domain", "scenario", "tech", "role", "hard", "negative")
HEADINGS = ("域词", "场景词", "技术词", "角色词", "硬要求", "排除词")


def lexicon_digest(lexicon: Lexicon) -> str:
    return canonical_digest(lexicon.model_dump(mode="json"))


def parse_lexicon(text: str) -> Lexicon:
    try:
        lines = text.lstrip("\ufeff").splitlines()
        if not lines or lines[0] != "---":
            raise ValueError("Header required.")
        end = lines.index("---", 1)
        metadata = yaml.safe_load("\n".join(lines[1:end]))
        if not isinstance(metadata, dict):
            raise ValueError("Header must be a mapping.")
        terms = []
        templates = []
        section = None
        fenced = False
        for raw in lines[end + 1 :]:
            line = raw.strip()
            if line.startswith(chr(96) * 3):
                fenced = not fenced
                continue
            if fenced:
                continue
            if line.startswith("## "):
                section = line.rsplit(" ", 1)[-1]
                continue
            if not line.startswith("- "):
                continue
            if section in DIMENSIONS:
                fields = [part.strip() for part in line[2:].split("|")]
                term: dict[str, object] = {"term": fields[0], "dimension": section}
                for field in fields[1:]:
                    key, value = field.split(":", 1)
                    if key.strip() in term:
                        raise ValueError("Duplicate field.")
                    term[key.strip()] = yaml.safe_load(value.strip())
                if not {"count", "last_seen", "source"} <= set(term):
                    raise ValueError("Required term metadata missing.")
                if term["last_seen"] == "-":
                    term["last_seen"] = None
                terms.append(term)
            elif section == "combinations":
                template = line[2:]
                if "：" in template:
                    template = template.split("：", 1)[1]
                elif ":" in template:
                    template = template.split(":", 1)[1]
                templates.append(template.strip())
        return Lexicon.model_validate({**metadata, "terms": terms, "combinations": templates})
    except (ValueError, TypeError, yaml.YAMLError, ValidationError) as error:
        raise ContractValidationError(
            "Lexicon Markdown does not satisfy the versioned format."
        ) from error


def serialize_lexicon(lexicon: Lexicon) -> str:
    metadata = lexicon.model_dump(mode="json", exclude={"terms", "combinations", "schema_version"})
    lines = [
        "---",
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip(),
        "---",
        "",
    ]
    for dimension, heading in zip(DIMENSIONS, HEADINGS, strict=True):
        lines.extend([f"## {heading} {dimension}", ""])
        for term in lexicon.terms:
            if term.dimension != dimension:
                continue
            fields = term.model_dump(mode="json", exclude={"schema_version", "term", "dimension"})
            parts = [term.term]
            for key, value in fields.items():
                parts.append(key + ": " + json.dumps(value, ensure_ascii=False))
            lines.append("- " + " | ".join(parts))
        lines.append("")
    lines.extend(["## 组合模板 combinations", ""])
    lines.extend("- " + template for template in lexicon.combinations)
    return "\n".join(lines) + "\n"
