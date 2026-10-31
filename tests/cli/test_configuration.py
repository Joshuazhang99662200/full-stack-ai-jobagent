import json

from typer.testing import CliRunner

from jobagent.cli.app import app
from tests.rules.test_preparation import preparation
from tests.storage.test_configuration import configured


def test_prepare_cli_is_readonly_and_only_initial_setup_can_ask(tmp_path):
    private = tmp_path / ".jobagent"
    private.mkdir()
    path = private / "preparation.json"
    db = private / "missing.sqlite3"
    runner = CliRunner()
    for mode, asks in [("ordinary_run", False), ("initial_setup", True)]:
        path.write_text(preparation(mode).model_dump_json(), encoding="utf-8")
        result = runner.invoke(app, ["rules", "prepare", str(path), "--database", str(db)])
        assert result.exit_code == 0, result.output
        output = json.loads(result.stdout)
        assert output["ask_user"] == asks and not db.exists()
        if not asks:
            assert output["questions"] == []


def test_prepare_cli_existing_profile_is_reused_without_prompting(tmp_path):
    root = tmp_path / ".jobagent"
    root.mkdir()
    db, _, _, snapshot = configured(root)
    path = root / "different-task.json"
    path.write_text(preparation("initial_setup").model_copy(
        update={"task_type": "new-task-type"},
    ).model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(app, ["rules", "prepare", str(path), "--database", str(db.path)])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["ready"] and body["rules_version"] == snapshot.version
    assert not body["ask_user"] and body["questions"] == []
