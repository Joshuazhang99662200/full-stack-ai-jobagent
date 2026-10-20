"""Add the read-only jobagent MCP server to the Claude Desktop config.

Run it only while Claude Desktop is fully closed: the app keeps its config in
memory and writes the whole file back when it quits, which would drop this entry.

    python scripts/register_jobagent_mcp.py
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"


def claude_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Claude.exe", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    return "Claude.exe" in out


def main() -> None:
    if claude_running():
        sys.exit("Claude Desktop is still running. Quit it from the tray icon, then rerun.")
    data = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    backup = CONFIG.with_name(f"claude_desktop_config.json.bak-{datetime.now():%Y%m%d%H%M%S}")
    if CONFIG.exists():
        shutil.copy2(CONFIG, backup)
    data.setdefault("mcpServers", {})["jobagent"] = {
        "command": sys.executable,
        "args": [
            "-m", "jobagent.bridge.mcp_server",
            "--database", str(REPO / ".jobagent" / "jobagent.sqlite3"),
        ],
        "env": {"PYTHONPATH": str(REPO / "src")},
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Added jobagent to {CONFIG}")
    print(f"Backup: {backup}")
    print("Now start Claude Desktop and check Settings > Developer for 'jobagent'.")


if __name__ == "__main__":
    main()
