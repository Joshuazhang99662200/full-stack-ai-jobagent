import type { MuseActions } from "./contracts";
import type { ConsoleDataSource } from "../dataSource";
import type { MuseOperationStore } from "./adapter";
import { hasVerifiedReadback } from "../hostService";

export type SyncKeys =
  | "getSelectionQueue"
  | "toggleSelectionItem"
  | "applySelectionOperation"
  | "executeSelectionDirect"
  | "executeJobDirect"
  | "regenerateGreeting"
  | "getGreetingSignals";
export type MuseSyncActions = Pick<MuseActions, SyncKeys>;
export type MuseCoreActions = Omit<MuseActions, SyncKeys>;
const active = new Set<string>();
const skipKey = (candidate: string, rank: number) =>
  `muse.sync.skips.${candidate}.${rank}`;
export function skippedHistory(
  store: MuseOperationStore,
  candidate: string,
  rank: number,
) {
  const rows = JSON.parse(store.load(skipKey(candidate, rank)) ?? "[]") as {
    detail: string;
    at: string;
  }[];
  return rows.map((r, index) => ({
    id: -index - 1,
    eventKind: "execution_skipped",
    occurredAt: r.at,
    occurredAtStatus: "已记录",
    detail: r.detail,
    isTransition: false,
    origin: "synthetic_panel",
  }));
}

/** Synthetic reference implementation. Real hosts inject the same RPCs backed by their services. */
export function createSyncActions(
  source: ConsoleDataSource,
  base: MuseCoreActions,
  store: MuseOperationStore,
  createSelectedBatch: (
    ranks: number[],
  ) => ReturnType<MuseActions["createExecutionBatch"]>,
  changed: () => void,
): MuseSyncActions {
  async function scope() {
    const s = (await base.getConsoleSnapshot({})).snapshot;
    const state = await source.getHostState();
    return { s, state };
  }
  function demoOnly() {
    if (source.mode !== "demo")
      throw new Error("服务端选择队列尚未接入，当前不能修改选择或快捷执行。");
  }
  async function selected() {
    demoOnly();
    const { s, state } = await scope();
    const key = `muse.sync.selection.${s.candidate_id}`;
    const saved = JSON.parse(store.load(key) ?? "[]") as
      | number[]
      | {
          version: number;
          candidate: string;
          ranks: number[];
          baseline: Record<number, string | null>;
        };
    const raw = Array.isArray(saved) ? saved : saved.ranks;
    if (
      !Array.isArray(raw) ||
      raw.some((n) => !Number.isInteger(n)) ||
      (!Array.isArray(saved) &&
        (saved.version !== 1 ||
          saved.candidate !== s.candidate_id ||
          !saved.baseline))
    )
      throw new Error("选择队列无效，未自动清空");
    const current = new Map<number, string>();
    for (const item of state.batches
      .flatMap((b) => b.items)
      .filter(hasVerifiedReadback)) {
      const row = s.jobs.find((j) => j.job.pipeline_id === item.contact_id);
      if (row) current.set(Number(row.job.host_rank), item.item_id);
    }
    const baseline: Record<number, string | null> = Array.isArray(saved)
      ? Object.fromEntries(raw.map((rank) => [rank, current.get(rank) ?? null]))
      : saved.baseline;
    const ranks = [...new Set(raw)]
      .filter(
        (rank) => !current.has(rank) || current.get(rank) === baseline[rank],
      )
      .sort((a, b) => a - b);
    if (JSON.stringify(raw) !== JSON.stringify(ranks))
      store.save(
        key,
        JSON.stringify({
          version: 1,
          candidate: s.candidate_id,
          ranks,
          baseline,
        }),
      );
    return { key, ranks, count: ranks.length, s, baseline, current };
  }
  async function write(ranks: number[]) {
    const c = await selected(),
      valid = new Set(c.s.jobs.map((j) => Number(j.job.host_rank)));
    if (ranks.some((rank) => !valid.has(rank)))
      throw new Error("选择包含未关联的岗位，已停止保存");
    const next = [...new Set(ranks)].sort((a, b) => a - b);
    const baseline = Object.fromEntries(
      next.map((rank) => [
        rank,
        c.ranks.includes(rank)
          ? (c.baseline[rank] ?? null)
          : (c.current.get(rank) ?? null),
      ]),
    );
    store.save(
      c.key,
      JSON.stringify({
        version: 1,
        candidate: c.s.candidate_id,
        ranks: next,
        baseline,
      }),
    );
    changed();
    return { ranks: next, count: next.length };
  }

  const reject = (message: string) => ({
    ok: false,
    error: "not_integrated",
    message,
    batchId: null,
    taskStarted: false,
  });
  async function execute(ranks: number[]) {
    demoOnly();
    const c = await selected();
    const candidate = c.s.candidate_id;
    if (active.has(candidate))
      return {
        ...reject("已有执行请求待核验，不能重复提交。"),
        queued: [],
        excluded: ranks.map((rank) => ({ rank, reason: "已有请求待核验" })),
      };
    active.add(candidate);
    try {
      const queued: number[] = [],
        excluded: { rank: number; reason: string }[] = [];
      for (const rank of [...new Set(ranks)]) {
        const prior = store.load(`muse.sync.request.${candidate}.${rank}`);
        let reason: string | null = null;
        if (prior) {
          const p = JSON.parse(prior) as { batchId: number };
          const it = (await base.getBatch({ batchId: p.batchId })).items.find(
            (i) => i.rank === rank,
          );
          if (
            !it ||
            !["done", "failed"].includes(it.status) ||
            (it.status === "failed" && !it.detail?.trim())
          )
            reason = "上次执行结果待核验，不能再次执行";
        }
        const check = await base.getExecPrecheck({ rank });
        reason ??= !check.approved
          ? "当前准确正文和附件尚未获批准"
          : !check.executable
            ? (check.blockReason ?? "当前不能执行")
            : null;
        if (reason) {
          excluded.push({ rank, reason });
          const key = skipKey(candidate, rank);
          const rows = JSON.parse(store.load(key) ?? "[]");
          rows.push({ detail: reason, at: new Date().toISOString() });
          store.save(key, JSON.stringify(rows));
        } else queued.push(rank);
      }
      if (!queued.length) {
        changed();
        return {
          ok: false,
          error: "not_executable",
          message: `成功 0 条、失败 0 条、拦下 ${excluded.length} 条；原因已归入各岗位进展与历史。`,
          batchId: null,
          taskStarted: false,
          queued: [],
          excluded,
        };
      }
      const batch = await createSelectedBatch(queued);
      excluded.push(...batch.excluded);
      if (batch.batchId == null || !batch.items.length)
        return { ...reject("没有可执行的已批准材料"), queued: [], excluded };
      for (const item of batch.items)
        store.save(
          `muse.sync.request.${candidate}.${item.rank}`,
          JSON.stringify({ batchId: batch.batchId }),
        );
      // Submission is acknowledged separately from task start and positive readback.
      void base
        .confirmExecution({ batchId: batch.batchId })
        .then(() => changed())
        .catch(() => changed());
      changed();
      return {
        ok: true,
        error: null,
        message:
          "执行请求已记录；是否启动及结果以逐项回读为准，可以继续处理其他岗位。",
        batchId: batch.batchId,
        taskStarted: false,
        queued: batch.items.map((i) => ({
          rank: i.rank,
          kind: i.kind,
          title: i.title,
          company: i.company,
          platform: i.platform,
        })),
        excluded,
      };
    } finally {
      active.delete(candidate);
    }
  }
  return {
    getSelectionQueue: async () => {
      const { ranks, count } = await selected();
      return { ranks, count };
    },
    toggleSelectionItem: async ({ rank, selected: yes }) => {
      const c = await selected();
      return write(
        yes ? [...c.ranks, rank] : c.ranks.filter((r) => r !== rank),
      );
    },
    applySelectionOperation: async ({ operation, visibleRanks }) => {
      const c = await selected();
      const set = new Set(c.ranks);
      if (operation === "clear_all") set.clear();
      else
        for (const rank of new Set(visibleRanks)) {
          if (
            operation === "clear_visible" ||
            (operation === "invert_visible" && set.has(rank))
          )
            set.delete(rank);
          else set.add(rank);
        }
      return write([...set]);
    },
    executeSelectionDirect: async () => execute((await selected()).ranks),
    executeJobDirect: async ({ rank }) => execute([rank]),
    regenerateGreeting: async () => ({
      ok: false,
      error: "not_integrated",
      message: "重新生成服务尚未接入",
      greeting: null,
      signalRecorded: false,
    }),
    getGreetingSignals: async ({ rank }) => {
      const { s, state } = await scope();
      const job = s.jobs.find((j) => Number(j.job.host_rank) === rank);
      if (!job) throw new Error("岗位来源未接入");
      const entry = state.jobs.find(
        (j) => j.contact_id === job.job.pipeline_id,
      );
      const signals = (entry?.events ?? [])
        .flatMap((e, index) => {
          if (e.kind !== "save_draft" || !e.material) return [];
          const version = entry!.materials.findIndex(
            (m) => m.revision === e.material?.revision,
          );
          const before = entry!.materials[version - 1]?.body ?? null;
          if (before === e.material.body) return [];
          return [
            {
              id: index + 1,
              kind: "manual_edit",
              beforeText: before,
              afterText: e.material.body,
              createdAt: e.occurred_at,
            },
          ];
        })
        .reverse();
      return { signals, count: signals.length };
    },
  };
}
