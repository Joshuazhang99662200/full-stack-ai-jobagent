"""Draft preparation and independent review over the existing outreach core."""

from datetime import datetime
from typing import TYPE_CHECKING

from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.outreach.service import OutreachService, contacted_job_ids
from jobagent.schemas.job_intake import IntakeBatch, IntakeDraft, IntakeRecord, IntakeReview
from jobagent.schemas.job_intelligence import HardFilterPolicy
from jobagent.schemas.jobs import FilterDecision, JobRequirementProfile
from jobagent.schemas.outreach import OutreachItem
from jobagent.storage.candidate_repository import SqliteCandidateRepository

if TYPE_CHECKING:
    from jobagent.storage.job_intake_service import JobIntakeService


class IntakeDraftingService:
    def __init__(self, intake: "JobIntakeService") -> None:
        self.intake = intake

    def validate_draft(self, row: IntakeRecord, submission: IntakeDraft) -> OutreachItem:
        job = self.intake.bound(row)
        if row.contacted or job.id in contacted_job_ids(self.intake.outreach.list_audits()):
            reject("Already contacted jobs continue through the existing conversation.")
        if submission.filter_context.candidate_id != row.candidate_id:
            reject("Filter context belongs to another candidate.")
        result = HardFilterEngine().evaluate(
            job,
            self.intake.jobs.get_requirements(job.id) or JobRequirementProfile(job_id=job.id),
            submission.filter_context,
            HardFilterPolicy(),
        )
        if result.decision != FilterDecision.PASS:
            reject("Hard constraints need a passing result; REVIEW is not approval.")
        evidence = SqliteCandidateRepository(self.intake.database).list_evidence(row.candidate_id)
        report = OutreachService().build_batch(
            [submission.draft],
            jobs={job.id: job},
            already_contacted=contacted_job_ids(self.intake.outreach.list_audits()),
            confirmed_evidence_ids=[e.id for e in evidence if e.user_confirmed],
            match_tiers=self.intake.jobs.latest_match_tiers(row.candidate_id, [job.id]),
            batch_id="OBATCH_INTAKE_VALIDATION",
            created_at=row.updated_at,
        )
        if report.batch is None or report.rejected:
            reject("Draft does not pass the existing outreach content and evidence rules.")
        return report.batch.items[0]

    def submit_draft(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeDraft.model_validate(data)
        row, digest, replay = self.intake.prepare(cmd, "draft")
        if replay:
            return row
        if not any(r.intent == "draft" for r in row.requests):
            reject("This intake authorizes inspection only.")
        self.validate_draft(row, cmd)
        return self.intake.commit(
            cmd,
            "draft",
            {
                "draft": cmd.draft,
                "draft_digest": canonical_digest(
                    [
                        row.snapshot_id,
                        cmd.draft.model_dump(mode="json"),
                        cmd.filter_context.model_dump(mode="json"),
                    ]
                ),
                "draft_author_reference": cmd.author_reference,
                "filter_context": cmd.filter_context,
                "review": None,
                "batch_id": None,
            },
            now,
            digest,
        )

    def review_draft(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeReview.model_validate(data)
        row, digest, replay = self.intake.prepare(cmd, "review")
        if replay:
            return row
        self.intake.bound(row)
        if (
            row.draft is None
            or row.draft_digest != cmd.draft_digest
            or row.snapshot_id != cmd.snapshot_id
            or row.draft_author_reference == cmd.reviewer_reference
            or (cmd.accepted and cmd.issues)
        ):
            reject(
                "Independent review must bind the current draft and snapshot without open issues."
            )
        return self.intake.commit(cmd, "review", {"review": cmd, "batch_id": None}, now, digest)

    def attach_batch(self, data: dict[str, object], *, now: datetime) -> IntakeRecord:
        cmd = IntakeBatch.model_validate(data)
        row, digest, replay = self.intake.prepare(cmd, "batch")
        if replay:
            return row
        if (
            row.review is None
            or not row.review.accepted
            or row.draft is None
            or row.filter_context is None
        ):
            reject("A current independently reviewed draft is required.")
        expected_item = self.validate_draft(
            row,
            IntakeDraft(
                **cmd.model_dump(exclude={"schema_version", "batch_id"}),
                draft=row.draft,
                author_reference=row.draft_author_reference or "",
                filter_context=row.filter_context,
            ),
        )
        batch = self.intake.outreach.get_batch(cmd.batch_id)
        if (
            batch is None
            or self.intake.outreach.is_withdrawn(cmd.batch_id)
            or not any(
                i.item_digest == expected_item.item_digest
                and i.job_id == row.job_id
                and i.platform == row.platform
                and i.text == row.draft.text
                and i.evidence_ids == row.draft.evidence_ids
                for i in batch.items
            )
        ):
            reject("Existing outreach batch does not contain this reviewed draft.")
        return self.intake.commit(cmd, "batch", {"batch_id": cmd.batch_id}, now, digest)
