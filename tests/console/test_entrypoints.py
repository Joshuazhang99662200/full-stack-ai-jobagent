import json

from typer.testing import CliRunner

from jobagent.bridge.mcp_server import McpServer
from jobagent.cli.app import app


def test_cli_queries_preserve_missing_source_diagnostics(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["console", "definitions"])
    assert result.exit_code == 0, result.output
    assert "jd_text" in result.stdout
    database = tmp_path / "absent.sqlite3"
    result = runner.invoke(
        app,
        ["console", "list", "CAND_DEMO", "--database", str(database), "--workspace", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["candidate_id"] == "CAND_DEMO"
    assert not database.exists()


def test_mcp_console_queries_share_same_contract(tmp_path):
    server = McpServer(tmp_path / ".jobagent/absent.sqlite3")
    for name, arguments in [
        ("console_definitions", {}),
        ("console_list", {"candidate_id": "CAND_DEMO"}),
    ]:
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        assert not response["result"]["isError"]
        payload = json.loads(response["result"]["content"][0]["text"])
        if name == "console_list":
            assert payload["candidate_id"] == "CAND_DEMO"
        else:
            assert "jd_text" in json.dumps(payload)


def test_mcp_explicit_workspace_matches_cli_for_custom_database_layout(tmp_path):
    from tests.console.test_console import setup_run

    workspace = tmp_path / "workspace"
    setup_run(workspace)
    database = tmp_path / "elsewhere" / "custom.sqlite3"
    server = McpServer(database, workspace=workspace)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "console_list", "arguments": {"candidate_id": "CAND_DEMO"}},
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    result = CliRunner().invoke(
        app,
        [
            "console",
            "list",
            "CAND_DEMO",
            "--database",
            str(database),
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0
    assert payload["runs"] == json.loads(result.stdout)["runs"]
    assert len(payload["runs"]) == 1
