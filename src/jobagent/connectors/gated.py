"""Platforms whose job descriptions are not publicly reachable.

BOSS 直聘 redirects an unauthenticated detail request to a security-verification
page, and 前程无忧 answers with an Aliyun WAF challenge. These are deliberate
bot-detection gates, not transient faults.

Reaching the JD anyway would require fingerprint spoofing, stealth browsers,
proxy rotation or CAPTCHA solving. This project does not do that: those states
translate to `USER_INTERVENTION_REQUIRED` and hand control back to the person,
who can open the posting in their own browser and supply the text.

Modelling them explicitly — rather than leaving them unimplemented — keeps the
workflow complete and makes the boundary visible instead of silent.
"""

from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord
from jobagent.schemas.sources import SourceManifest


class GatedJobSource:
    """Report a platform gate as a typed pause, with a usable manual route."""

    def __init__(self, manifest: SourceManifest) -> None:
        if manifest.gate is None:
            raise ContractValidationError(
                "This source declares no gate.", details={"source": manifest.id}
            )
        self._manifest = manifest
        self._gate = manifest.gate

    @property
    def source(self) -> str:
        return self._manifest.id

    def fetch(self, listing: JobListing) -> SourceJobRecord:
        raise self.gate_error(job_id=listing.source_job_id, url=str(listing.url))

    def gate_error(
        self, *, job_id: str | None = None, url: str | None = None
    ) -> UserInterventionRequiredError:
        manifest, gate = self._manifest, self._gate
        return UserInterventionRequiredError(
            f"{manifest.display_name} does not expose this job description publicly.",
            details={
                "source": manifest.id,
                "job_id": job_id,
                "url": url,
                "gate": gate.gate,
                "detail": gate.detail,
                "manual_route": gate.manual_route,
                "never": "不绕过验证、不伪装指纹、不轮换账号或代理。",
            },
        )


