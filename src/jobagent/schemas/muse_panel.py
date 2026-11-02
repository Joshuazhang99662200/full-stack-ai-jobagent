"""Muse RPC view contracts; these never replace canonical business models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class MuseView(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MuseGetTableDataRequest(MuseView):
    pass


class MuseGetTableDataResponseRowsItem(MuseView):
    rank: float
    title: str
    company: str
    platform: str
    channel: str
    location: str | None
    salary: str | None
    jobUrl: str | None
    matchBullets: list[str]
    matchScore: float | None
    progress: str | None
    progressStale: bool
    progressError: str | None
    progressUpdatedAt: str | None
    state: str
    intakeAt: str | None
    contacted: bool
    waiting: bool


class MuseGetTableDataResponse(MuseView):
    rows: list[MuseGetTableDataResponseRowsItem]
    pendingProgress: float
    failedProgress: float


class MuseGetJobRequest(MuseView):
    rank: int


class MuseGetJobResponseJob(MuseView):
    rank: float
    platform: str
    title: str
    company: str
    location: str | None
    salary: str | None
    jobUrl: str | None
    hostStatus: str
    state: str
    stateLabel: str
    group: str
    blocked: bool
    blockedKind: str | None
    blockedNote: str | None
    hasDraft: bool
    deliveryResult: str | None
    latestDecisionKind: str | None
    historyCount: float


class MuseGetJobResponseDecisionsItem(MuseView):
    id: float
    kind: str
    note: str | None
    greetingText: str | None
    status: str
    createdAt: str


class MuseGetJobResponseHistoryItem(MuseView):
    id: float
    eventKind: str
    occurredAt: str | None
    occurredAtStatus: str
    detail: str
    isTransition: bool
    origin: str


class MuseGetJobResponse(MuseView):
    job: MuseGetJobResponseJob | None
    jdPoints: list[str]
    gaps: list[str]
    draftGreeting: str | None
    approvedGreeting: str | None
    draftVersion: str | None
    completeness: str | None
    matchStrengths: list[str]
    matchPartial: list[str]
    matchUncertainties: list[str]
    matchHardGaps: list[str]
    hardFilterReasons: list[str]
    sendStatus: str | None
    deliveryStatus: str | None
    progress: str | None
    progressStale: bool
    progressError: str | None
    channel: str
    matchLabel: str
    matchScore: float | None
    decisions: list[MuseGetJobResponseDecisionsItem]
    history: list[MuseGetJobResponseHistoryItem]


class MuseGetJobMaterialsRequest(MuseView):
    rank: int


class MuseGetJobMaterialsResponseSentGreetingsItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponseGreetingVersionsItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponseFeedbackItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponsePanelSyncItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponseDeliveriesItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponseCvFilesItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponseCommSnapshotsItem(MuseView):
    id: float
    title: str
    body: str
    occurredAt: str | None
    source: str | None


class MuseGetJobMaterialsResponse(MuseView):
    sentGreetings: list[MuseGetJobMaterialsResponseSentGreetingsItem]
    greetingVersions: list[MuseGetJobMaterialsResponseGreetingVersionsItem]
    feedback: list[MuseGetJobMaterialsResponseFeedbackItem]
    panelSync: list[MuseGetJobMaterialsResponsePanelSyncItem]
    deliveries: list[MuseGetJobMaterialsResponseDeliveriesItem]
    cvFiles: list[MuseGetJobMaterialsResponseCvFilesItem]
    commSnapshots: list[MuseGetJobMaterialsResponseCommSnapshotsItem]


class MuseGetTodosRequest(MuseView):
    pass


class MuseGetTodosResponseJobsItemItemsItem(MuseView):
    id: str
    kind: Literal["greeting", "execution", "block", "review"]
    action: str
    question: str
    reasons: list[str]


class MuseGetTodosResponseJobsItem(MuseView):
    rank: float
    title: str
    company: str
    platform: str
    location: str | None
    salary: str | None
    matchOverall: float | None
    matchStrengths: list[str]
    matchPartial: list[str]
    matchUncertainties: list[str]
    items: list[MuseGetTodosResponseJobsItemItemsItem]


class MuseGetTodosResponse(MuseView):
    jobCount: float
    itemCount: float
    jobs: list[MuseGetTodosResponseJobsItem]


class MuseGetBatchRequest(MuseView):
    batchId: int


class MuseGetBatchResponseBatch(MuseView):
    id: float
    status: str
    createdAt: str


class MuseGetBatchResponseItemsItem(MuseView):
    rank: float
    kind: str
    status: str
    detail: str | None
    title: str
    company: str
    platform: str


class MuseGetBatchResponse(MuseView):
    batch: MuseGetBatchResponseBatch | None
    items: list[MuseGetBatchResponseItemsItem]


class MuseGetChannelLoginRequest(MuseView):
    pass


class MuseGetChannelLoginResponseChannelsItem(MuseView):
    channel: str
    status: str
    checkedAt: str | None
    restoreRequestedAt: str | None
    restoreStatus: str


class MuseGetChannelLoginResponse(MuseView):
    channels: list[MuseGetChannelLoginResponseChannelsItem]


class MuseGetConsoleSnapshotRequest(MuseView):
    pass


class MuseGetConsoleSnapshotResponseSnapshotSourcesItem(MuseView):
    name: str
    status: str
    message: str | None


class MuseGetConsoleSnapshotResponseSnapshotJobsItem(MuseView):
    job: dict[str, object]
    meta: dict[str, object]
    history: list[dict[str, object]]
    match_result: dict[str, object] | None
    match_context: dict[str, object] | None
    hard_filter_result: dict[str, object] | None
    hard_filter_context: dict[str, object] | None


class MuseGetConsoleSnapshotResponseSnapshotRunsItem(MuseView):
    run: dict[str, object]
    activities: list[dict[str, object]]
    freshness: str


class MuseGetConsoleSnapshotResponseSnapshot(MuseView):
    schema_version: Literal["1.0"]
    candidate_id: str
    generated_at: str
    sources: list[MuseGetConsoleSnapshotResponseSnapshotSourcesItem]
    jobs: list[MuseGetConsoleSnapshotResponseSnapshotJobsItem]
    runs: list[MuseGetConsoleSnapshotResponseSnapshotRunsItem]
    approvals: list[dict[str, object]]


class MuseGetConsoleSnapshotResponse(MuseView):
    seeded: bool
    matchComplete: bool
    queueReconcileNeeded: bool
    matchCount: float
    hardCounts: dict[str, float]
    lastImport: str | None
    snapshot: MuseGetConsoleSnapshotResponseSnapshot


class MuseGetReviewBriefRequest(MuseView):
    rank: int


class MuseGetReviewBriefResponse(MuseView):
    points: list[str]
    keywords: list[str]
    incomplete: bool
    note: str | None


class MuseGetExecPrecheckRequest(MuseView):
    rank: int


class MuseGetExecPrecheckResponse(MuseView):
    found: bool
    rank: float
    platform: str
    channel: str
    title: str
    company: str
    location: str | None
    salary: str | None
    kind: str
    state: str
    approved: bool
    needsApproval: bool
    executable: bool
    greetingText: str | None
    blockReason: str | None
    familyRanks: list[float]


class MuseGetOnlineResumeRequest(MuseView):
    pass


class MuseGetOnlineResumeResponse(MuseView):
    recordedAt: str
    text: str


class MuseGetRecoveryReportRequest(MuseView):
    pass


class MuseGetRecoveryReportResponse(MuseView):
    seeded: bool
    itemCount: float
    report: object


class MuseRecordDecisionRequest(MuseView):
    rank: int
    kind: Literal[
        "accept_original",
        "accept_revise",
        "decline",
        "deliver",
        "skip",
        "close",
        "reopen",
        "resolve_block",
        "approve_text",
    ]
    note: str | None
    greetingText: str | None


class MuseRecordDecisionResponse(MuseView):
    ok: bool
    error: str | None
    message: str | None
    decisionId: float | None
    writebackStarted: bool


class MuseSaveGreetingDraftRequest(MuseView):
    rank: int
    text: str


class MuseSaveGreetingDraftResponse(MuseView):
    ok: bool
    error: str | None
    message: str | None


class MuseCreateExecutionBatchRequest(MuseView):
    pass


class MuseCreateExecutionBatchResponseItemsItem(MuseView):
    rank: float
    kind: str
    title: str
    company: str
    platform: str
    greetingPreview: str | None


class MuseCreateExecutionBatchResponseExcludedItem(MuseView):
    rank: float
    reason: str


class MuseCreateExecutionBatchResponse(MuseView):
    batchId: float | None
    status: str
    items: list[MuseCreateExecutionBatchResponseItemsItem]
    excluded: list[MuseCreateExecutionBatchResponseExcludedItem]


class MuseCreateJobExecutionBatchRequest(MuseView):
    rank: int


class MuseCreateJobExecutionBatchResponseItemsItem(MuseView):
    rank: float
    kind: str
    title: str
    company: str
    platform: str
    greetingPreview: str | None


class MuseCreateJobExecutionBatchResponseExcludedItem(MuseView):
    rank: float
    reason: str


class MuseCreateJobExecutionBatchResponse(MuseView):
    batchId: float | None
    status: str
    items: list[MuseCreateJobExecutionBatchResponseItemsItem]
    excluded: list[MuseCreateJobExecutionBatchResponseExcludedItem]


class MuseConfirmExecutionRequest(MuseView):
    batchId: int


class MuseConfirmExecutionResponse(MuseView):
    ok: bool
    error: str | None
    message: str | None
    taskStarted: bool


class MuseSyncFromHostRequest(MuseView):
    pass


class MuseSyncFromHostResponse(MuseView):
    started: bool
    message: str


class MuseRequestLoginRestoreRequest(MuseView):
    channel: str


class MuseRequestLoginRestoreResponse(MuseView):
    ok: bool
    error: str | None
    message: str | None
    requestedAt: str | None
    requestId: str | None
    taskStarted: bool


class MuseGenerateProgressRequest(MuseView):
    limit: int
    force: bool


class MuseGenerateProgressResponseFailuresItem(MuseView):
    rank: float
    reason: str


class MuseGenerateProgressResponse(MuseView):
    generated: float
    corrected: float
    remaining: float
    failures: list[MuseGenerateProgressResponseFailuresItem]


class MuseSeedFromSnapshotRequest(MuseView):
    pass


class MuseSeedFromSnapshotResponse(MuseView):
    seeded: bool
    jobs: float
    events: float


class MuseRepairMatchFromSnapshotRequest(MuseView):
    pass


class MuseRepairMatchFromSnapshotResponse(MuseView):
    repaired: float
    jobs: float
    matchCount: float
    hardPass: float
    hardReview: float
    hardReject: float


class MuseReconcileToQueueRequest(MuseView):
    pass


class MuseReconcileToQueueResponseRevertedItem(MuseView):
    rank: float
    detail: str


class MuseReconcileToQueueResponse(MuseView):
    reverted: list[MuseReconcileToQueueResponseRevertedItem]
    hostStatusCounts: dict[str, float]
    stateCounts: dict[str, float]


class MuseSyncNewJobsRequest(MuseView):
    pass


class MuseSyncNewJobsResponse(MuseView):
    inserted: float
    jobs: float
    statusCounts: dict[str, float]
    intakeCount: float
    newRanksPresent: list[float]


MUSE_RPC_MODELS = {
    "getTableData": (MuseGetTableDataRequest, MuseGetTableDataResponse),
    "getJob": (MuseGetJobRequest, MuseGetJobResponse),
    "getJobMaterials": (MuseGetJobMaterialsRequest, MuseGetJobMaterialsResponse),
    "getTodos": (MuseGetTodosRequest, MuseGetTodosResponse),
    "getBatch": (MuseGetBatchRequest, MuseGetBatchResponse),
    "getChannelLogin": (MuseGetChannelLoginRequest, MuseGetChannelLoginResponse),
    "getConsoleSnapshot": (MuseGetConsoleSnapshotRequest, MuseGetConsoleSnapshotResponse),
    "getReviewBrief": (MuseGetReviewBriefRequest, MuseGetReviewBriefResponse),
    "getExecPrecheck": (MuseGetExecPrecheckRequest, MuseGetExecPrecheckResponse),
    "getOnlineResume": (MuseGetOnlineResumeRequest, MuseGetOnlineResumeResponse),
    "getRecoveryReport": (MuseGetRecoveryReportRequest, MuseGetRecoveryReportResponse),
    "recordDecision": (MuseRecordDecisionRequest, MuseRecordDecisionResponse),
    "saveGreetingDraft": (MuseSaveGreetingDraftRequest, MuseSaveGreetingDraftResponse),
    "createExecutionBatch": (MuseCreateExecutionBatchRequest, MuseCreateExecutionBatchResponse),
    "createJobExecutionBatch": (
        MuseCreateJobExecutionBatchRequest,
        MuseCreateJobExecutionBatchResponse,
    ),
    "confirmExecution": (MuseConfirmExecutionRequest, MuseConfirmExecutionResponse),
    "syncFromHost": (MuseSyncFromHostRequest, MuseSyncFromHostResponse),
    "requestLoginRestore": (MuseRequestLoginRestoreRequest, MuseRequestLoginRestoreResponse),
    "generateProgress": (MuseGenerateProgressRequest, MuseGenerateProgressResponse),
    "seedFromSnapshot": (MuseSeedFromSnapshotRequest, MuseSeedFromSnapshotResponse),
    "repairMatchFromSnapshot": (
        MuseRepairMatchFromSnapshotRequest,
        MuseRepairMatchFromSnapshotResponse,
    ),
    "reconcileToQueue": (MuseReconcileToQueueRequest, MuseReconcileToQueueResponse),
    "syncNewJobs": (MuseSyncNewJobsRequest, MuseSyncNewJobsResponse),
}
