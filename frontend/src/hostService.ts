import type { JobView } from "./contracts";
import type {
  HostJob,
  HostState,
  HostSync,
  HostSyncDifference,
  HostTodo,
  HostEvent,
  HostExecutionItem,
} from "./hostContracts";

/** Scraped fields only. All other fields retain their existing owner and history. */
const scraped = [
  "title",
  "company",
  "location",
  "job_url",
  "salary_raw",
  "salary_min_k",
  "salary_max_k",
  "salary_verified",
  "jd_text",
  "jd_text_hash",
  "jd_points",
];
export function mergeJobFacts(previous: JobView, incoming: JobView): JobView {
  if (
    previous.job.job_id !== incoming.job.job_id ||
    previous.job.pipeline_id !== incoming.job.pipeline_id ||
    previous.job.candidate_id !== incoming.job.candidate_id
  )
    throw new Error("同步记录不属于同一个岗位与联系轮次");
  const job = { ...previous.job };
  for (const key of scraped)
    if (Object.hasOwn(incoming.job, key)) job[key] = incoming.job[key];
  return {
    ...previous,
    job,
    match_result: incoming.match_result,
    match_context: incoming.match_context,
    hard_filter_result: incoming.hard_filter_result,
    hard_filter_context: incoming.hard_filter_context,
  };
}

export interface HostSyncPort {
  readPlatform(): Promise<void>;
  importHostFacts(): Promise<void>;
  exportPanelRecords(): Promise<void>;
  compareCounts(): Promise<HostSyncDifference[]>;
}
const syncing = new WeakSet<HostSyncPort>();
export async function synchronizeHost(
  port: HostSyncPort,
  clock: () => string,
): Promise<HostSync> {
  if (syncing.has(port))
    return {
      status: "unknown",
      message: "已有同步正在核对，请稍后查看结果。",
      differences: [],
      checked_at: null,
    };
  syncing.add(port);
  try {
    await port.readPlatform();
    await port.importHostFacts();
    await port.exportPanelRecords();
    const differences = await port.compareCounts();
    return {
      status: differences.length ? "mismatch" : "current",
      differences,
      checked_at: clock(),
      message: differences.length
        ? "同步后仍有岗位不一致，需核对下面的差异。"
        : "已核对回读并完成同步，双方数量一致。",
    };
  } catch {
    return {
      status: "failed",
      message: "同步未完成，当前显示保留的旧记录。",
      differences: [],
      checked_at: null,
    };
  } finally {
    syncing.delete(port);
  }
}

export const currentMaterial = (job: HostJob) => job.materials.at(-1);
export const latestDecision = (job: HostJob) =>
  [...job.events]
    .reverse()
    .find((e) => ["approve_material", "decline"].includes(e.kind));
export function personalTodos(state: HostState): HostTodo[] {
  return state.todos.filter(
    (t) =>
      t.status === "pending" &&
      t.requires_person &&
      t.host_resolved &&
      t.basis.length > 0 &&
      t.options.length > 0 &&
      state.jobs.some(
        (j) => j.job_id === t.job_id && j.contact_id === t.contact_id,
      ),
  );
}
/** Collapse duplicate display entries without mutating the authoritative event chain. */
export function displayHistory(events: HostEvent[]): HostEvent[] {
  const visible = new Map<string, HostEvent>();
  for (const event of events) {
    const key = JSON.stringify([
      event.job_id,
      event.contact_id,
      event.operation_key,
    ]);
    visible.delete(key);
    visible.set(key, event);
  }
  return [...visible.values()];
}
export function safeMaterialUrl(url: string): string | null {
  try {
    const parsed = new URL(url, "https://console.invalid");
    return ["https:", "http:"].includes(parsed.protocol) &&
      !parsed.username &&
      !parsed.password
      ? url
      : null;
  } catch {
    return null;
  }
}

export function hasVerifiedReadback(item: HostExecutionItem): boolean {
  return (
    item.selected &&
    item.status === "verified" &&
    item.readback?.status === "verified" &&
    !!item.readback.evidence &&
    !!item.readback.observed_at &&
    Number.isFinite(Date.parse(item.readback.observed_at)) &&
    item.readback.material_revision === item.material.revision
  );
}
