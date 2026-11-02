"""Generate Muse RPC view types from the authoritative Python transport models."""

import argparse
import json
from pathlib import Path
from typing import Any

from jobagent.schemas.muse_panel import MUSE_RPC_MODELS

OUTPUT = Path(__file__).resolve().parents[1] / "frontend/src/muse/contracts.ts"


def ts_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return str(schema["$ref"]).split("/")[-1]
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(ts_type(value) for value in schema["anyOf"])
    kind = schema.get("type")
    if kind == "array":
        return f"Array<{ts_type(schema['items'])}>"
    if kind == "object":
        value = schema.get("additionalProperties", {})
        return f"Record<string, {ts_type(value) if isinstance(value, dict) else 'unknown'}>"
    return {
        "string": "string",
        "number": "number",
        "integer": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind, "unknown")


def generate() -> str:
    models: dict[str, dict[str, Any]] = {}
    for pair in MUSE_RPC_MODELS.values():
        for model in pair:
            schema = model.model_json_schema()
            models.update(schema.pop("$defs", {}))
            models[model.__name__] = schema
    lines = ["// Generated from src/jobagent/schemas/muse_panel.py. Do not edit."]
    for name, schema in sorted(models.items()):
        lines.append(f"export interface {name} {{")
        for key, value in schema["properties"].items():
            lines.append(f"  {key}: {ts_type(value)};")
        lines.append("}")
    lines.append("export interface MuseActions {")
    for name, (request, response) in MUSE_RPC_MODELS.items():
        lines.append(f"  {name}(args: {request.__name__}): Promise<{response.__name__}>;")
    lines += [
        "}",
        "export declare const api: MuseActions;",
        "export type ApiResponse<T, K extends keyof T> = "
        "T[K] extends (...args: never[]) => infer R ? Awaited<R> : never;",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            raise SystemExit("Muse view types are stale; run scripts/build_muse_contracts.py")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(generated, encoding="utf-8")
