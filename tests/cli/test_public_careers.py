import json

from typer.testing import CliRunner

from jobagent.cli.app import app


def test_public_list_missing_database_is_structured_and_creates_nothing(tmp_path):
    path = tmp_path / "missing.sqlite3"
    result = CliRunner().invoke(
        app, ["public-careers", "list", "--candidate-id", "CAND_SYNTHETIC", "--database", str(path)]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    assert not path.exists()
