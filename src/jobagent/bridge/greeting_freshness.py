"""Recheck the live sources behind an AI-reviewed greeting before approval or send."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from jobagent.errors import JobAgentError, StaleApprovalError
from jobagent.outreach.generation import content_digest
from jobagent.reasoning.job_matcher import is_admissible
from jobagent.schemas.greeting import GreetingJob
from jobagent.schemas.outreach import OutreachDraft, OutreachItem
from jobagent.skill_resources import read_reference
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


class _SnapshotDatabase(Database):
    """Let existing repositories read the same read-only SQLite transaction."""

    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        super().__init__(path)
        self.connection = connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        yield self.connection


def _stale(reason: str) -> Never:
    raise StaleApprovalError(
        "The AI greeting source snapshot is stale or incomplete.",
        details={"reason": reason},
    )


def verify_greeting_sources(
    database: Database,
    items: Sequence[OutreachDraft | OutreachItem],
    *,
    candidate_id: str | None = None,
) -> None:
    """Verify bound sources only; legacy drafts keep their existing approval path.

    A missing or changed source is a stale result, never permission to regenerate,
    approve or send. Source text is deliberately absent from error diagnostics.
    """
    bound = []
    for item in items:
        if item.source_binding is None:
            if item.variant == "whole-message.v1":
                _stale("missing_source_binding")
        else:
            bound.append(item)
    if not bound:
        return

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(database.path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        snapshot = _SnapshotDatabase(database.path, connection)
        candidates = SqliteCandidateRepository(snapshot)
        jobs = SqliteJobRepository(snapshot)
        policy_digest = content_digest(read_reference("references/greeting-ai.md"))
        for item in bound:
            binding = item.source_binding
            assert binding is not None
            if candidate_id is not None and binding.candidate_id != candidate_id:
                _stale("candidate_mismatch")
            if (len(set(binding.evidence_ids)) != len(binding.evidence_ids)
                    or not set(item.evidence_ids) <= set(binding.evidence_ids)):
                _stale("evidence_reference_mismatch")
            available = {
                evidence.id: evidence
                for evidence in candidates.list_evidence(binding.candidate_id)
            }
            if any(eid not in available or not is_admissible(available[eid])
                   for eid in binding.evidence_ids):
                _stale("evidence_missing_or_unconfirmed")
            source_evidence = [
                available[eid].model_dump(mode="json") for eid in binding.evidence_ids
            ]
            if content_digest(source_evidence) != binding.evidence_digest:
                _stale("evidence_changed")
            job = jobs.get_job(item.job_id)
            if job is None:
                _stale("job_missing")
            target = GreetingJob(
                job_id=job.id, company=job.company, title=job.title, platform=job.source,
                url=str(job.url), jd_raw=job.jd_raw,
            )
            if (item.platform != job.source
                    or content_digest(target.model_dump(mode="json")) != binding.job_digest):
                _stale("job_changed")
            if content_digest(item.text) != binding.text_digest:
                _stale("text_changed")
            if policy_digest != binding.policy_digest:
                _stale("policy_changed")
    except StaleApprovalError:
        raise
    except (sqlite3.Error, JobAgentError, ValidationError, OSError):
        _stale("source_unavailable_or_invalid")
    finally:
        if connection is not None:
            connection.close()
