"""Last stored candidate/job assessment snapshots, never fresh evaluations."""

import sqlite3
from datetime import datetime

from jobagent.schemas.console import ConsoleFilterContext, ConsoleJob, ConsoleMatchContext
from jobagent.schemas.jobs import HardFilterResult, MatchResult


def _key(row: sqlite3.Row) -> tuple[datetime, str, str, str, str]:
    timestamp = datetime.fromisoformat(row["updated_at"])
    if timestamp.tzinfo is None:
        raise ValueError("Assessment timestamp has no timezone")
    columns = set(row.keys())
    return (
        timestamp,
        row["job_id"],
        row["policy_digest"],
        row["evidence_digest"] if "evidence_digest" in columns else "",
        row["requirements_digest"] if "requirements_digest" in columns else "",
    )


def attach_assessments(connection: sqlite3.Connection, item: ConsoleJob) -> bool:
    valid = True
    identities = [item.job.job_id]
    if item.meta.normalized_job_id and item.meta.normalized_job_id not in identities:
        identities.append(item.meta.normalized_job_id)
    marks = ",".join("?" for _ in identities)
    for table in ("job_matches", "hard_filter_results"):
        try:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE candidate_id=? AND job_id IN ({marks})",
                (item.job.candidate_id, *identities),
            ).fetchall()
            if not rows:
                continue
            # Compare actual instants, not text offsets. Digests break equal-time ties reproducibly.
            latest = max(rows, key=_key)
            context = dict(
                job_id=latest["job_id"],
                updated_at=latest["updated_at"],
                policy_digest=latest["policy_digest"],
            )
            if table == "job_matches":
                match = MatchResult.model_validate_json(latest["result_json"])
                match_context = ConsoleMatchContext(
                    **context,
                    evidence_digest=latest["evidence_digest"],
                    requirements_digest=latest["requirements_digest"],
                )
                item.match_result = match
                item.match_context = match_context
            else:
                filtered = HardFilterResult.model_validate_json(latest["result_json"])
                filter_context = ConsoleFilterContext(**context)
                item.hard_filter_result = filtered
                item.hard_filter_context = filter_context
        except (sqlite3.Error, ValueError, TypeError):
            valid = False
    return valid
