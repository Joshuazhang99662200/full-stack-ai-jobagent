"""Read-only public board orchestration with explicit units and conservative geography."""

from collections.abc import Callable
from datetime import UTC, datetime

from jobagent.connectors.public_careers import identity, parse_board
from jobagent.connectors.public_careers_http import ControlledPublicHttp
from jobagent.errors import ContractValidationError, JobAgentError, UserInterventionRequiredError
from jobagent.jobs.public_careers import BUDGET_NAMES, region_decision
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.public_careers import (
    PublicCareerConfig,
    PublicCareerDisposition,
    PublicCareerRecord,
    PublicCareerRun,
)
from jobagent.storage.public_careers_repository import SqlitePublicCareersRepository


class PublicCareersService:
    def __init__(
        self,
        repository: SqlitePublicCareersRepository,
        transport: ControlledPublicHttp | None = None,
    ) -> None:
        self.repository = repository
        self.transport = transport or ControlledPublicHttp()

    def run(
        self,
        candidate_id: str,
        config: PublicCareerConfig,
        rules: DynamicRuleSet,
        run_id: str,
        *,
        cancel: Callable[[], bool] = lambda: False,
    ) -> PublicCareerRun:
        validate_snapshot(rules)
        if candidate_id != rules.candidate_id or candidate_id != config.filter_context.candidate_id:
            raise ContractValidationError("Public careers candidate scope mismatch.")
        missing = [name for name in BUDGET_NAMES if name not in rules.values]
        if missing:
            raise ContractValidationError(
                "Public careers confirmed budgets are not configured.", details={"missing": missing}
            )
        if not config.filter_context.allowed_locations:
            raise ContractValidationError("Public careers needs explicit existing location policy.")
        budgets = {name: int(str(rules.values[name])) for name in BUDGET_NAMES}
        run = PublicCareerRun(
            run_id=run_id,
            candidate_id=candidate_id,
            rules_version=rules.version,
            started_at=datetime.now(UTC),
            budgets=budgets,
            config=config,
        )
        self.repository.start(run)
        incomplete = False
        first_incomplete: str | None = None
        for board in config.boards:
            run.resume_board = board.source
            self.repository.save_run(run)
            if cancel():
                run.status = "cancelled"
                break
            if self.repository.stopped(candidate_id, board.provider):
                run.status = "paused"
                run.errors.append(f"{board.source}: persistent source stop requires owner review.")
                break
            receipt: str | None = None

            def dispatch(source: str = board.source) -> None:
                nonlocal receipt
                receipt = self.repository.reserve_http(run, source)
                run.http_attempts += 1
                run.query_attempts += 1
                self.repository.save_run(run)

            try:
                body = self.transport.get(
                    board,
                    max_bytes=budgets["PUBLIC_CAREERS_MAX_BYTES"],
                    timeout=budgets["PUBLIC_CAREERS_TIMEOUT_SECONDS"],
                    dispatch=dispatch,
                    cancel=cancel,
                )
                assert receipt is not None
                self.repository.finish_http(receipt, body, None)
                page = parse_board(board, body)
                run.raw_returned += page.raw_returned
                run.missing_jd += page.missing_jd
                run.invalid += page.invalid
                run.observed += len(page.records)
                dispositions = [
                    PublicCareerDisposition(
                        source=board.source, input_index=index, disposition="invalid"
                    )
                    for index in range(page.raw_returned)
                ]
                run.dispositions.extend(dispositions)
                candidates = []
                for item in page.records:
                    disposition = dispositions[item.input_index]
                    disposition.source_job_id = item.listing.source_job_id
                    disposition.disposition = "deferred"
                    decision = region_decision(item.listing.location, config.filter_context)
                    if decision == "reject":
                        disposition.disposition = "rejected"
                        continue
                    run.eligible += 1
                    candidates.append((item, decision))
                for item, decision in candidates[: budgets["TOP_PER_QUERY"]]:
                    record = PublicCareerRecord(
                        candidate_id=candidate_id,
                        provider=board.provider,
                        board=board.board,
                        source_job_id=item.listing.source_job_id,
                        job_id=identity(board.source, item.listing.source_job_id),
                        run_id=run_id,
                        listing=item.listing,
                        observation=item.observation,
                        region_decision=decision,
                    )
                    if self.repository.save_record(record):
                        run.duplicate += 1
                        dispositions[item.input_index].disposition = "duplicate"
                    else:
                        dispositions[item.input_index].disposition = "taken"
                    run.taken += 1
                limited = len(candidates) > budgets["TOP_PER_QUERY"]
                incomplete |= bool(page.truncated or page.invalid or page.missing_jd or limited)
                if (
                    page.truncated or page.invalid or page.missing_jd or limited
                ) and first_incomplete is None:
                    first_incomplete = board.source
                if page.truncated or limited:
                    run.errors.append(
                        f"{board.source}: partial; narrow configured board scope or "
                        "review confirmed take limit; no automatic re-read."
                    )
                else:
                    run.boards_completed.append(board.source)
                    run.resume_board = None
            except (JobAgentError, OSError, ValueError) as error:
                message = str(error)
                if isinstance(error, UserInterventionRequiredError):
                    self.repository.stop(candidate_id, board.provider, message)
                if receipt is not None:
                    # Preserve an already-received raw payload if parsing/import failed.
                    self.repository.finish_http_error(receipt, message)
                if isinstance(error, UserInterventionRequiredError):
                    run.status = "paused"
                else:
                    run.status = "cancelled" if cancel() else ("partial" if run.taken else "failed")
                run.errors.append(f"{board.source}: {message}")
                break
            finally:
                self.repository.save_run(run)
        if run.status == "running":
            run.status = "partial" if incomplete else "complete"
        if run.status == "partial" and first_incomplete is not None:
            run.resume_board = first_incomplete
        self.repository.save_run(run)
        return run
