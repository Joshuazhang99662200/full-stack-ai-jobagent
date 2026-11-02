// Generated from src/jobagent/schemas/muse_panel.py. Do not edit.
export interface MuseConfirmExecutionRequest {
  batchId: number;
}
export interface MuseConfirmExecutionResponse {
  ok: boolean;
  error: string | null;
  message: string | null;
  taskStarted: boolean;
}
export interface MuseCreateExecutionBatchRequest {
}
export interface MuseCreateExecutionBatchResponse {
  batchId: number | null;
  status: string;
  items: Array<MuseCreateExecutionBatchResponseItemsItem>;
  excluded: Array<MuseCreateExecutionBatchResponseExcludedItem>;
}
export interface MuseCreateExecutionBatchResponseExcludedItem {
  rank: number;
  reason: string;
}
export interface MuseCreateExecutionBatchResponseItemsItem {
  rank: number;
  kind: string;
  title: string;
  company: string;
  platform: string;
  greetingPreview: string | null;
}
export interface MuseCreateJobExecutionBatchRequest {
  rank: number;
}
export interface MuseCreateJobExecutionBatchResponse {
  batchId: number | null;
  status: string;
  items: Array<MuseCreateJobExecutionBatchResponseItemsItem>;
  excluded: Array<MuseCreateJobExecutionBatchResponseExcludedItem>;
}
export interface MuseCreateJobExecutionBatchResponseExcludedItem {
  rank: number;
  reason: string;
}
export interface MuseCreateJobExecutionBatchResponseItemsItem {
  rank: number;
  kind: string;
  title: string;
  company: string;
  platform: string;
  greetingPreview: string | null;
}
export interface MuseGenerateProgressRequest {
  limit: number;
  force: boolean;
}
export interface MuseGenerateProgressResponse {
  generated: number;
  corrected: number;
  remaining: number;
  failures: Array<MuseGenerateProgressResponseFailuresItem>;
}
export interface MuseGenerateProgressResponseFailuresItem {
  rank: number;
  reason: string;
}
export interface MuseGetBatchRequest {
  batchId: number;
}
export interface MuseGetBatchResponse {
  batch: MuseGetBatchResponseBatch | null;
  items: Array<MuseGetBatchResponseItemsItem>;
}
export interface MuseGetBatchResponseBatch {
  id: number;
  status: string;
  createdAt: string;
}
export interface MuseGetBatchResponseItemsItem {
  rank: number;
  kind: string;
  status: string;
  detail: string | null;
  title: string;
  company: string;
  platform: string;
}
export interface MuseGetChannelLoginRequest {
}
export interface MuseGetChannelLoginResponse {
  channels: Array<MuseGetChannelLoginResponseChannelsItem>;
}
export interface MuseGetChannelLoginResponseChannelsItem {
  channel: string;
  status: string;
  checkedAt: string | null;
  restoreRequestedAt: string | null;
  restoreStatus: string;
}
export interface MuseGetConsoleSnapshotRequest {
}
export interface MuseGetConsoleSnapshotResponse {
  seeded: boolean;
  matchComplete: boolean;
  queueReconcileNeeded: boolean;
  matchCount: number;
  hardCounts: Record<string, number>;
  lastImport: string | null;
  snapshot: MuseGetConsoleSnapshotResponseSnapshot;
}
export interface MuseGetConsoleSnapshotResponseSnapshot {
  schema_version: "1.0";
  candidate_id: string;
  generated_at: string;
  sources: Array<MuseGetConsoleSnapshotResponseSnapshotSourcesItem>;
  jobs: Array<MuseGetConsoleSnapshotResponseSnapshotJobsItem>;
  runs: Array<MuseGetConsoleSnapshotResponseSnapshotRunsItem>;
  approvals: Array<Record<string, unknown>>;
}
export interface MuseGetConsoleSnapshotResponseSnapshotJobsItem {
  job: Record<string, unknown>;
  meta: Record<string, unknown>;
  history: Array<Record<string, unknown>>;
  match_result: Record<string, unknown> | null;
  match_context: Record<string, unknown> | null;
  hard_filter_result: Record<string, unknown> | null;
  hard_filter_context: Record<string, unknown> | null;
}
export interface MuseGetConsoleSnapshotResponseSnapshotRunsItem {
  run: Record<string, unknown>;
  activities: Array<Record<string, unknown>>;
  freshness: string;
}
export interface MuseGetConsoleSnapshotResponseSnapshotSourcesItem {
  name: string;
  status: string;
  message: string | null;
}
export interface MuseGetExecPrecheckRequest {
  rank: number;
}
export interface MuseGetExecPrecheckResponse {
  found: boolean;
  rank: number;
  platform: string;
  channel: string;
  title: string;
  company: string;
  location: string | null;
  salary: string | null;
  kind: string;
  state: string;
  approved: boolean;
  needsApproval: boolean;
  executable: boolean;
  greetingText: string | null;
  blockReason: string | null;
  familyRanks: Array<number>;
}
export interface MuseGetJobMaterialsRequest {
  rank: number;
}
export interface MuseGetJobMaterialsResponse {
  sentGreetings: Array<MuseGetJobMaterialsResponseSentGreetingsItem>;
  greetingVersions: Array<MuseGetJobMaterialsResponseGreetingVersionsItem>;
  feedback: Array<MuseGetJobMaterialsResponseFeedbackItem>;
  panelSync: Array<MuseGetJobMaterialsResponsePanelSyncItem>;
  deliveries: Array<MuseGetJobMaterialsResponseDeliveriesItem>;
  cvFiles: Array<MuseGetJobMaterialsResponseCvFilesItem>;
  commSnapshots: Array<MuseGetJobMaterialsResponseCommSnapshotsItem>;
}
export interface MuseGetJobMaterialsResponseCommSnapshotsItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobMaterialsResponseCvFilesItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobMaterialsResponseDeliveriesItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobMaterialsResponseFeedbackItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobMaterialsResponseGreetingVersionsItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobMaterialsResponsePanelSyncItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobMaterialsResponseSentGreetingsItem {
  id: number;
  title: string;
  body: string;
  occurredAt: string | null;
  source: string | null;
}
export interface MuseGetJobRequest {
  rank: number;
}
export interface MuseGetJobResponse {
  job: MuseGetJobResponseJob | null;
  jdPoints: Array<string>;
  gaps: Array<string>;
  draftGreeting: string | null;
  approvedGreeting: string | null;
  draftVersion: string | null;
  completeness: string | null;
  matchStrengths: Array<string>;
  matchPartial: Array<string>;
  matchUncertainties: Array<string>;
  matchHardGaps: Array<string>;
  hardFilterReasons: Array<string>;
  sendStatus: string | null;
  deliveryStatus: string | null;
  progress: string | null;
  progressStale: boolean;
  progressError: string | null;
  channel: string;
  matchLabel: string;
  matchScore: number | null;
  decisions: Array<MuseGetJobResponseDecisionsItem>;
  history: Array<MuseGetJobResponseHistoryItem>;
}
export interface MuseGetJobResponseDecisionsItem {
  id: number;
  kind: string;
  note: string | null;
  greetingText: string | null;
  status: string;
  createdAt: string;
}
export interface MuseGetJobResponseHistoryItem {
  id: number;
  eventKind: string;
  occurredAt: string | null;
  occurredAtStatus: string;
  detail: string;
  isTransition: boolean;
  origin: string;
}
export interface MuseGetJobResponseJob {
  rank: number;
  platform: string;
  title: string;
  company: string;
  location: string | null;
  salary: string | null;
  jobUrl: string | null;
  hostStatus: string;
  state: string;
  stateLabel: string;
  group: string;
  blocked: boolean;
  blockedKind: string | null;
  blockedNote: string | null;
  hasDraft: boolean;
  deliveryResult: string | null;
  latestDecisionKind: string | null;
  historyCount: number;
}
export interface MuseGetOnlineResumeRequest {
}
export interface MuseGetOnlineResumeResponse {
  recordedAt: string;
  text: string;
}
export interface MuseGetRecoveryReportRequest {
}
export interface MuseGetRecoveryReportResponse {
  seeded: boolean;
  itemCount: number;
  report: unknown;
}
export interface MuseGetReviewBriefRequest {
  rank: number;
}
export interface MuseGetReviewBriefResponse {
  points: Array<string>;
  keywords: Array<string>;
  incomplete: boolean;
  note: string | null;
}
export interface MuseGetTableDataRequest {
}
export interface MuseGetTableDataResponse {
  rows: Array<MuseGetTableDataResponseRowsItem>;
  pendingProgress: number;
  failedProgress: number;
}
export interface MuseGetTableDataResponseRowsItem {
  rank: number;
  title: string;
  company: string;
  platform: string;
  channel: string;
  location: string | null;
  salary: string | null;
  jobUrl: string | null;
  matchBullets: Array<string>;
  matchScore: number | null;
  progress: string | null;
  progressStale: boolean;
  progressError: string | null;
  progressUpdatedAt: string | null;
  state: string;
  intakeAt: string | null;
  contacted: boolean;
  waiting: boolean;
}
export interface MuseGetTodosRequest {
}
export interface MuseGetTodosResponse {
  jobCount: number;
  itemCount: number;
  jobs: Array<MuseGetTodosResponseJobsItem>;
}
export interface MuseGetTodosResponseJobsItem {
  rank: number;
  title: string;
  company: string;
  platform: string;
  location: string | null;
  salary: string | null;
  matchOverall: number | null;
  matchStrengths: Array<string>;
  matchPartial: Array<string>;
  matchUncertainties: Array<string>;
  items: Array<MuseGetTodosResponseJobsItemItemsItem>;
}
export interface MuseGetTodosResponseJobsItemItemsItem {
  id: string;
  kind: "greeting" | "execution" | "block" | "review";
  action: string;
  question: string;
  reasons: Array<string>;
}
export interface MuseReconcileToQueueRequest {
}
export interface MuseReconcileToQueueResponse {
  reverted: Array<MuseReconcileToQueueResponseRevertedItem>;
  hostStatusCounts: Record<string, number>;
  stateCounts: Record<string, number>;
}
export interface MuseReconcileToQueueResponseRevertedItem {
  rank: number;
  detail: string;
}
export interface MuseRecordDecisionRequest {
  rank: number;
  kind: "accept_original" | "accept_revise" | "decline" | "deliver" | "skip" | "close" | "reopen" | "resolve_block" | "approve_text";
  note: string | null;
  greetingText: string | null;
}
export interface MuseRecordDecisionResponse {
  ok: boolean;
  error: string | null;
  message: string | null;
  decisionId: number | null;
  writebackStarted: boolean;
}
export interface MuseRepairMatchFromSnapshotRequest {
}
export interface MuseRepairMatchFromSnapshotResponse {
  repaired: number;
  jobs: number;
  matchCount: number;
  hardPass: number;
  hardReview: number;
  hardReject: number;
}
export interface MuseRequestLoginRestoreRequest {
  channel: string;
}
export interface MuseRequestLoginRestoreResponse {
  ok: boolean;
  error: string | null;
  message: string | null;
  requestedAt: string | null;
  requestId: string | null;
  taskStarted: boolean;
}
export interface MuseSaveGreetingDraftRequest {
  rank: number;
  text: string;
}
export interface MuseSaveGreetingDraftResponse {
  ok: boolean;
  error: string | null;
  message: string | null;
}
export interface MuseSeedFromSnapshotRequest {
}
export interface MuseSeedFromSnapshotResponse {
  seeded: boolean;
  jobs: number;
  events: number;
}
export interface MuseSyncFromHostRequest {
}
export interface MuseSyncFromHostResponse {
  started: boolean;
  message: string;
}
export interface MuseSyncNewJobsRequest {
}
export interface MuseSyncNewJobsResponse {
  inserted: number;
  jobs: number;
  statusCounts: Record<string, number>;
  intakeCount: number;
  newRanksPresent: Array<number>;
}
export interface MuseActions {
  getTableData(args: MuseGetTableDataRequest): Promise<MuseGetTableDataResponse>;
  getJob(args: MuseGetJobRequest): Promise<MuseGetJobResponse>;
  getJobMaterials(args: MuseGetJobMaterialsRequest): Promise<MuseGetJobMaterialsResponse>;
  getTodos(args: MuseGetTodosRequest): Promise<MuseGetTodosResponse>;
  getBatch(args: MuseGetBatchRequest): Promise<MuseGetBatchResponse>;
  getChannelLogin(args: MuseGetChannelLoginRequest): Promise<MuseGetChannelLoginResponse>;
  getConsoleSnapshot(args: MuseGetConsoleSnapshotRequest): Promise<MuseGetConsoleSnapshotResponse>;
  getReviewBrief(args: MuseGetReviewBriefRequest): Promise<MuseGetReviewBriefResponse>;
  getExecPrecheck(args: MuseGetExecPrecheckRequest): Promise<MuseGetExecPrecheckResponse>;
  getOnlineResume(args: MuseGetOnlineResumeRequest): Promise<MuseGetOnlineResumeResponse>;
  getRecoveryReport(args: MuseGetRecoveryReportRequest): Promise<MuseGetRecoveryReportResponse>;
  recordDecision(args: MuseRecordDecisionRequest): Promise<MuseRecordDecisionResponse>;
  saveGreetingDraft(args: MuseSaveGreetingDraftRequest): Promise<MuseSaveGreetingDraftResponse>;
  createExecutionBatch(args: MuseCreateExecutionBatchRequest): Promise<MuseCreateExecutionBatchResponse>;
  createJobExecutionBatch(args: MuseCreateJobExecutionBatchRequest): Promise<MuseCreateJobExecutionBatchResponse>;
  confirmExecution(args: MuseConfirmExecutionRequest): Promise<MuseConfirmExecutionResponse>;
  syncFromHost(args: MuseSyncFromHostRequest): Promise<MuseSyncFromHostResponse>;
  requestLoginRestore(args: MuseRequestLoginRestoreRequest): Promise<MuseRequestLoginRestoreResponse>;
  generateProgress(args: MuseGenerateProgressRequest): Promise<MuseGenerateProgressResponse>;
  seedFromSnapshot(args: MuseSeedFromSnapshotRequest): Promise<MuseSeedFromSnapshotResponse>;
  repairMatchFromSnapshot(args: MuseRepairMatchFromSnapshotRequest): Promise<MuseRepairMatchFromSnapshotResponse>;
  reconcileToQueue(args: MuseReconcileToQueueRequest): Promise<MuseReconcileToQueueResponse>;
  syncNewJobs(args: MuseSyncNewJobsRequest): Promise<MuseSyncNewJobsResponse>;
}
export declare const api: MuseActions;
export type ApiResponse<T, K extends keyof T> = T[K] extends (...args: never[]) => infer R ? Awaited<R> : never;
