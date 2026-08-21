"""Deterministic, provenance-preserving job deduplication."""

import hashlib
import re
from collections.abc import Sequence

from jobagent.schemas.job_intelligence import (
    DeduplicationPolicy,
    DeduplicationResult,
    DuplicateGroup,
)
from jobagent.schemas.jobs import NormalizedJob


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", _normalized(value)))


def _similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    union = left_tokens | right_tokens
    return 1.0 if not union else len(left_tokens & right_tokens) / len(union)


class JobDeduplicator:
    """Merge equivalent observations without discarding their sources."""

    def deduplicate(
        self,
        jobs: Sequence[NormalizedJob],
        policy: DeduplicationPolicy,
    ) -> DeduplicationResult:
        ordered = sorted((job.model_copy(deep=True) for job in jobs), key=lambda job: job.id)
        parents = list(range(len(ordered)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[max(left_root, right_root)] = min(left_root, right_root)

        for left in range(len(ordered)):
            for right in range(left + 1, len(ordered)):
                if self._are_duplicates(ordered[left], ordered[right], policy):
                    union(left, right)

        grouped: dict[int, list[NormalizedJob]] = {}
        for index, job in enumerate(ordered):
            grouped.setdefault(find(index), []).append(job)

        merged_jobs: list[NormalizedJob] = []
        duplicate_groups: list[DuplicateGroup] = []
        for members in grouped.values():
            merged = self._merge(members)
            merged_jobs.append(merged)
            if len(members) > 1:
                duplicate_groups.append(
                    DuplicateGroup(
                        canonical_job_id=merged.id,
                        member_job_ids=sorted(member.id for member in members),
                        reason="exact or near duplicate source observations",
                    )
                )
        return DeduplicationResult(
            jobs=sorted(merged_jobs, key=lambda job: job.id),
            duplicate_groups=sorted(
                duplicate_groups,
                key=lambda group: group.canonical_job_id,
            ),
        )

    @staticmethod
    def _are_duplicates(
        left: NormalizedJob,
        right: NormalizedJob,
        policy: DeduplicationPolicy,
    ) -> bool:
        same_identity = (
            _normalized(left.company) == _normalized(right.company)
            and _normalized(left.title) == _normalized(right.title)
            and _normalized(left.location) == _normalized(right.location)
        )
        if not same_identity:
            return False
        if _normalized(left.jd_raw) == _normalized(right.jd_raw):
            return True
        return _similarity(left.jd_raw, right.jd_raw) >= policy.near_duplicate_threshold

    @staticmethod
    def _merge(members: Sequence[NormalizedJob]) -> NormalizedJob:
        if len(members) == 1:
            return members[0].model_copy(deep=True)

        ordered = sorted(members, key=lambda job: (job.collected_at, job.id))
        base = ordered[0]
        richest_jd = sorted(
            members,
            key=lambda job: (-len(_tokens(job.jd_raw)), -len(job.jd_raw), job.id),
        )[0]
        provenance = sorted(
            {
                (
                    item.source,
                    item.source_id,
                    str(item.url) if item.url is not None else "",
                    item.collected_at.isoformat(),
                ): item
                for job in members
                for item in job.provenance
            }.values(),
            key=lambda item: (
                item.source.casefold(),
                item.source_id.casefold(),
                item.collected_at,
            ),
        )
        identity = "\0".join(
            sorted(f"{item.source.casefold()}:{item.source_id.casefold()}" for item in provenance)
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        salary_values = {
            job.salary.model_dump_json() for job in members if job.salary is not None
        }
        recruiter_values = {
            job.recruiter.model_dump_json() for job in members if job.recruiter is not None
        }
        warnings = {warning for job in members for warning in job.warnings}
        if len(salary_values) > 1:
            warnings.add("SALARY_CONFLICT")
        if len(recruiter_values) > 1:
            warnings.add("RECRUITER_CONFLICT")
        salary = next((job.salary for job in ordered if job.salary is not None), None)
        recruiter = next((job.recruiter for job in ordered if job.recruiter is not None), None)
        published_values = [job.published_at for job in members if job.published_at is not None]
        return NormalizedJob(
            id=f"JOB_{digest[:16].upper()}",
            source=base.source,
            source_job_id=base.source_job_id,
            title=base.title,
            company=base.company,
            location=base.location,
            salary=salary,
            jd_raw=richest_jd.jd_raw,
            recruiter=recruiter,
            url=base.url,
            published_at=max(published_values) if published_values else None,
            collected_at=base.collected_at,
            provenance=provenance,
            warnings=sorted(warnings),
        )
