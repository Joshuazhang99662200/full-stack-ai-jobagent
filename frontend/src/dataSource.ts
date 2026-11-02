import type { Definitions, JobView, Snapshot } from "./contracts";
import type {
  HostBatch,
  HostDecisionRequest,
  HostExecutionRequest,
  HostMaterial,
  HostReceipt,
  HostState,
  HostSync,
} from "./hostContracts";

/** Host transport; mutations must delegate to existing business services and approval gates. */
export interface ConsoleDataSource {
  mode: "snapshot" | "host" | "demo";
  getSnapshot(signal?: AbortSignal): Promise<Snapshot>;
  getDefinitions(signal?: AbortSignal): Promise<Definitions>;
  getJob(jobId: string, contactId: string): Promise<JobView | null>;
  getMaterials(jobId: string, contactId: string): Promise<HostMaterial[]>;
  getHostState(signal?: AbortSignal): Promise<HostState>;
  getTodos(): Promise<HostState["todos"]>;
  getChannelLogin(): Promise<HostState["channels"]>;
  getBatch(batchId: string): Promise<HostBatch | null>;
  recordDecision?(request: HostDecisionRequest): Promise<HostReceipt>;
  getOperation?(key: string): Promise<HostReceipt>;
  createExecutionBatch?(contactIds: string[]): Promise<HostBatch>;
  confirmExecution?(request: HostExecutionRequest): Promise<HostReceipt>;
  requestLoginRestore?(channel: string): Promise<HostReceipt>;
  synchronize?(): Promise<HostSync>;
}

export const unavailableHost = (candidateId: string): HostState => ({
  protocol_version: "1.0",
  candidate_id: candidateId,
  jobs: [],
  todos: [],
  channels: [],
  batches: [],
  receipts: [],
  sync: {
    status: "unavailable",
    message: "宿主交互尚未接入，当前只能查看已有记录。",
    checked_at: null,
    differences: [],
  },
});

export function checkSnapshot(value: Snapshot): Snapshot {
  if (
    value?.schema_version !== "1.0" ||
    !value.candidate_id ||
    !Array.isArray(value.jobs) ||
    !Array.isArray(value.runs) ||
    !Array.isArray(value.sources) ||
    value.jobs.some((j) => j.job.candidate_id !== value.candidate_id)
  )
    throw new Error("收到的数据格式或候选人范围与当前页面不匹配");
  return value;
}

export function createSnapshotSource(
  snapshot: Snapshot,
  definitions: Definitions = {},
): ConsoleDataSource {
  checkSnapshot(snapshot);
  return {
    mode: "snapshot",
    getSnapshot: async () => structuredClone(snapshot),
    getDefinitions: async () => definitions,
    getJob: async (jobId, contactId) =>
      structuredClone(
        snapshot.jobs.find(
          (j) => j.job.job_id === jobId && j.job.pipeline_id === contactId,
        ) ?? null,
      ),
    getMaterials: async () => [],
    getHostState: async () => unavailableHost(snapshot.candidate_id),
    getTodos: async () => [],
    getChannelLogin: async () => [],
    getBatch: async () => null,
  };
}

/** Only existing GET endpoints; no invented write endpoint or silent demo fallback. */
export function createHttpSource(): ConsoleDataSource {
  async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
    const response = await fetch(path, { cache: "no-store", signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  const source: ConsoleDataSource = {
    ...createSnapshotSource({
      schema_version: "1.0",
      candidate_id: "UNLOADED",
      generated_at: "",
      jobs: [],
      runs: [],
      sources: [],
      approvals: [],
    }),
    getSnapshot: async (signal) =>
      checkSnapshot(await get<Snapshot>("/api/snapshot", signal)),
    getDefinitions: (signal) => get<Definitions>("/api/definitions", signal),
    getJob: async (jobId, contactId) =>
      (await source.getSnapshot()).jobs.find(
        (j) => j.job.job_id === jobId && j.job.pipeline_id === contactId,
      ) ?? null,
    getHostState: async () => unavailableHost("UNLOADED"),
  };
  return source;
}
