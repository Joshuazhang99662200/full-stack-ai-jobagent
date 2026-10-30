import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.errors import StaleApprovalError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


def test_draft_batch_checks_reviewed_sources_before_saving(tmp_path, monkeypatch):
    database = Database(tmp_path / "binding.sqlite3")
    database.migrate()
    job = JobNormalizer().normalize(SourceJobRecord(
        source="manual", source_job_id="synthetic", title="AI PM", company="Synthetic",
        location="Shanghai",
        jd_raw="Build document research agents and evaluate model output quality.",
        url="https://jobs.example.test/synthetic", collected_at=datetime.now(UTC),
    ))
    SqliteJobRepository(database).save_job(job)
    path = tmp_path / "drafts.json"
    path.write_text(json.dumps([{
        "job_id": job.id, "platform": "manual", "text": "Hello, can we talk?",
    }]), encoding="utf-8")
    seen = []
    def reject(db, drafts, *, candidate_id=None):
        seen.append((db.path, len(drafts), candidate_id))
        raise StaleApprovalError("Source changed.")
    monkeypatch.setattr("jobagent.cli.outreach.verify_greeting_sources", reject)
    result = CliRunner().invoke(app, [
        "outreach", "draft-batch", str(path), "--database", str(database.path),
    ])
    assert result.exit_code == 1 and seen == [(database.path, 1, None)]
    assert json.loads(result.stdout)["error"]["code"] == "STALE_APPROVAL"
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM outreach_batches").fetchone()[0] == 0
