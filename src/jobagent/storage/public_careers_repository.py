"""Candidate-scoped public discovery facts; projections never migrate a database."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.jobs.sourcing import SOURCING_DAY
from jobagent.schemas.public_careers import PublicCareerRecord, PublicCareerRun
from jobagent.storage.database import Database


def business_day(now: datetime) -> str:
    return now.astimezone(SOURCING_DAY).date().isoformat()


class SqlitePublicCareersRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_records(self, candidate_id: str) -> list[PublicCareerRecord]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT record_json FROM public_career_records WHERE candidate_id=? ORDER BY rowid",
                (candidate_id,),
            )
            return [PublicCareerRecord.model_validate_json(row[0]) for row in rows]

    def list_runs(self, candidate_id: str) -> list[PublicCareerRun]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT run_json FROM public_career_runs WHERE candidate_id=? ORDER BY rowid",
                (candidate_id,),
            )
            return [PublicCareerRun.model_validate_json(row[0]) for row in rows]

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        if not self.database.path.is_file():
            raise ContractValidationError("Public careers database is missing.")
        connection = sqlite3.connect(f"{self.database.path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()

    def start(self, run: PublicCareerRun) -> None:
        with self.database.connect() as connection, connection:
            previous = connection.execute(
                "SELECT 1 FROM public_career_runs WHERE run_id=?", (run.run_id,)
            ).fetchone()
            if previous:
                raise ContractValidationError(
                    "Run identity already exists; inspect before restart."
                )
            connection.execute(
                "INSERT INTO public_career_runs VALUES (?,?,?)",
                (run.run_id, run.candidate_id, run.model_dump_json()),
            )

    def save_run(self, run: PublicCareerRun) -> None:
        with self.database.connect() as connection, connection:
            connection.execute(
                "UPDATE public_career_runs SET run_json=? WHERE run_id=?",
                (run.model_dump_json(), run.run_id),
            )

    def stopped(self, candidate_id: str, provider: str) -> bool:
        with self.database.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM public_career_stops WHERE candidate_id=? AND provider=?",
                    (candidate_id, provider),
                ).fetchone()
                is not None
            )

    def stop(self, candidate_id: str, provider: str, reason: str) -> None:
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO public_career_stops VALUES (?,?,?)",
                (candidate_id, provider, reason),
            )

    def reserve_http(self, run: PublicCareerRun, source: str) -> str:
        """Atomically debit shared channel/day/source/round before dispatch."""
        now = datetime.now(UTC).astimezone(SOURCING_DAY).isoformat()
        with self.database.transaction() as connection:
            provider = source.split(":")[1]
            stopped = connection.execute(
                "SELECT 1 FROM public_career_stops WHERE candidate_id=? AND provider=?",
                (run.candidate_id, provider),
            ).fetchone()
            if stopped:
                raise UserInterventionRequiredError("Public provider has a persistent stop.")
            head = connection.execute(
                "SELECT version FROM dynamic_rule_heads WHERE candidate_id=?", (run.candidate_id,)
            ).fetchone()
            if not head or head[0] != run.rules_version:
                raise ContractValidationError("Public careers requires current confirmed rules.")
            unknown = connection.execute(
                "SELECT 1 FROM public_career_http WHERE candidate_id=? AND outcome='dispatched'",
                (run.candidate_id,),
            ).fetchone()
            if unknown:
                raise ContractValidationError("Unknown previous HTTP result requires verification.")
            day = connection.execute(
                "SELECT count(*) FROM public_career_http WHERE candidate_id=? "
                "AND substr(dispatched_at,1,10)=?",
                (run.candidate_id, now[:10]),
            ).fetchone()[0]
            round_count = connection.execute(
                "SELECT count(*) FROM public_career_http WHERE run_id=?", (run.run_id,)
            ).fetchone()[0]
            board_count = connection.execute(
                "SELECT count(*) FROM public_career_http "
                "WHERE candidate_id=? AND source=? "
                "AND substr(dispatched_at,1,10)=?",
                (run.candidate_id, source, now[:10]),
            ).fetchone()[0]
            if (
                day >= run.budgets["PUBLIC_CAREERS_HTTP_PER_DAY"]
                or round_count
                >= min(
                    run.budgets["PUBLIC_CAREERS_HTTP_PER_ROUND"],
                    run.budgets["PUBLIC_CAREERS_QUERY_PER_ROUND"],
                )
                or board_count >= run.budgets["PUBLIC_CAREERS_HTTP_PER_BOARD"]
            ):
                raise ContractValidationError("Public careers request budget exhausted.")
            receipt_id = uuid4().hex
            connection.execute(
                "INSERT INTO public_career_http VALUES (?,?,?,?,?,?,NULL,NULL)",
                (receipt_id, run.run_id, run.candidate_id, source, now, "dispatched"),
            )
            return receipt_id

    def finish_http(self, receipt_id: str, body: bytes | None, error: str | None) -> None:
        with self.database.connect() as connection, connection:
            connection.execute(
                "UPDATE public_career_http SET outcome=?, response=?, error=? WHERE receipt_id=?",
                ("failed" if error else "received", body, error, receipt_id),
            )

    def finish_http_error(self, receipt_id: str, error: str) -> None:
        with self.database.connect() as connection, connection:
            connection.execute(
                "UPDATE public_career_http SET outcome='failed', error=? WHERE receipt_id=?",
                (error, receipt_id),
            )

    def save_record(self, record: PublicCareerRecord) -> bool:
        from jobagent.jobs.normalization import JobNormalizer
        from jobagent.storage.job_repository import SqliteJobRepository

        with self.database.transaction() as connection:
            exists = (
                connection.execute(
                    "SELECT 1 FROM public_career_records WHERE candidate_id=? "
                    "AND provider=? AND board=? AND source_job_id=?",
                    (record.candidate_id, record.provider, record.board, record.source_job_id),
                ).fetchone()
                is not None
            )
            if record.observation is not None:
                job = JobNormalizer().normalize(record.observation)
                SqliteJobRepository(self.database).save_observation(
                    record.observation, job, connection=connection
                )
            connection.execute(
                "INSERT OR REPLACE INTO public_career_records VALUES (?,?,?,?,?,?,?)",
                (
                    record.candidate_id,
                    record.provider,
                    record.board,
                    record.source_job_id,
                    record.job_id,
                    record.run_id,
                    record.model_dump_json(),
                ),
            )
            return exists
