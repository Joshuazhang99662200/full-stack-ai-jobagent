import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { api, ApiResponse } from "./contracts";
import {
  useMuseActions,
  useMuseConfiguration,
  useMuseCvFiles,
} from "./context";

type TodosResp = ApiResponse<typeof api, "getTodos">;
type BatchEcho = ApiResponse<typeof api, "createExecutionBatch">;
type JobMaterials = ApiResponse<typeof api, "getJobMaterials">;
type ChannelLoginResp = ApiResponse<typeof api, "getChannelLogin">;
function LoginRestoreEntry({
  channel,
  compact,
}: {
  channel: ChannelLoginResp["channels"][number];
  compact?: boolean;
}) {
  const api = useMuseActions();
  const policy = useMuseConfiguration();
  const queryClient = useQueryClient();
  const [justRequested, setJustRequested] = useState(false);
  const [failed, setFailed] = useState(false);
  const restore = useMutation({
    mutationFn: () => api.requestLoginRestore({ channel: channel.channel }),
    onSuccess: (r) => {
      if (r.ok && r.taskStarted) {
        setJustRequested(true);
        setFailed(false);
      } else {
        setJustRequested(false);
        setFailed(true);
      }
      void queryClient.invalidateQueries({ queryKey: ["channel-login"] });
    },
    onError: () => {
      setJustRequested(false);
      setFailed(true);
    },
  });
  if (channel.status !== "dropped") return null;
  const recovering =
    channel.restoreStatus === "requested" ||
    channel.restoreStatus === "opened" ||
    (justRequested && channel.restoreStatus !== "failed");
  const showFailed =
    !recovering && (failed || channel.restoreStatus === "failed");
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className={compact ? "text-sm" : "text-sm font-medium"}>
        {channel.channel} 登录已失效
        {channel.checkedAt ? (
          <span className="text-[var(--dim)]">
            （{channel.checkedAt} 核对）
          </span>
        ) : null}
      </span>
      {recovering ? (
        <span
          className="inline-flex min-h-[36px] items-center rounded-[var(--radius)] border border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
          role="status"
        >
          恢复中
        </span>
      ) : (
        <>
          <button
            type="button"
            aria-label="恢复登录"
            className="inline-flex min-h-[36px] items-center rounded-[var(--radius)] bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
            disabled={restore.isPending}
            onClick={() => restore.mutate()}
          >
            {restore.isPending ? "正在发起…" : "恢复登录"}
          </button>
          {showFailed && (
            <span className="text-sm text-[var(--danger)]" role="alert">
              没发起成功，请再点一次。
            </span>
          )}
        </>
      )}
    </span>
  );
}

function droppedChannelFor(
  channels: ChannelLoginResp["channels"] | undefined,
  platform: string,
): ChannelLoginResp["channels"][number] | null {
  if (!channels) return null;
  return (
    channels.find(
      (c) =>
        c.status === "dropped" &&
        ((c.channel === "BOSS" && platform.includes("BOSS")) ||
          (c.channel === "智联" && platform.includes("智联")) ||
          (c.channel === "猎聘" && platform.includes("猎聘"))),
    ) ?? null
  );
}

const MATCH_DECISION_CN: Record<string, string> = {
  strong_match: "经历与要求比较接近",
  possible_match: "有对得上的经历",
  weak_match: "对得上的地方不多",
  not_a_match: "与要求差距较大",
};
const HARD_FILTER_CN: Record<string, string> = {
  PASS: "基本要求符合",
  REVIEW: "基本要求有一项待确认",
  REJECT: "基本要求不符合",
};

export function plainText(text: string): string {
  let out = text;
  out = out.replace(
    /匹配分=(\d+(?:\.\d+)?)，决定=(strong_match|possible_match|weak_match|not_a_match)，硬筛=(PASS|REVIEW|REJECT)/g,
    (_m, score: string, dec: string, hf: string) =>
      `要点匹配 ${Math.round(parseFloat(score) * 100)} 分，${MATCH_DECISION_CN[dec] ?? dec}，${HARD_FILTER_CN[hf] ?? hf}`,
  );
  out = out.replace(/；?JD要点\+宿主工作记录撞公共算法（权重\/阈值原样）/g, "");
  if (out.includes("卡片决定=accept")) {
    out = out.replace("卡片决定=accept", "已记录文案选择：接受");
  }
  if (out.includes("卡片决定=reject")) {
    out = out.replace("卡片决定=reject", "已记录文案选择：不接受");
  }
  out = out.replace(
    /招呼稿版本=[^；。]+；稿件全文见队列，不在此重复全文/g,
    "招呼语已写好",
  );
  out = out.replace(/；回读见队列\s*send_readback/g, "；招呼语已发送");
  out = out.replace(/回读见队列\s*send_readback/g, "招呼语已发送");
  out = out.replace(/稿件全文见队列，不在此重复全文/g, "招呼语已写好");
  out = out.replace(/招呼稿版本=[^\s；。]+/g, "招呼语已写好");
  out = out.replace(/见队列\s*send_readback/g, "招呼语已发送");
  out = out.replace(/全文见队列/g, "全文见招呼语");
  out = out.replace(/见队列/g, "见招呼语");
  return out;
}
function displayCompany(name: string | null | undefined): string {
  const n = (name ?? "").trim();
  if (!n) return "待核实";
  if (/某|匿名/.test(n)) return "【猎头岗位】";
  return n;
}

const DECISION_KIND_LABELS: Record<string, string> = {
  accept_original: "批准这份材料",
  accept_revise: "帮我改一下",
  decline: "放弃这个岗位",
  deliver: "确认投递",
  skip: "先放一放",
  close: "关闭岗位",
  reopen: "继续了解",
  resolve_block: "解除阻塞（用户判定）",
  approve_text: "这版文案可以",
};

type MainTab = "progress" | "runs" | "comms" | "about";
type JobFilter = "all" | "active" | "todo" | "waiting" | "contacted" | "ended";

export function rowMatchesFilter(
  r: TableRow,
  filter: JobFilter,
  todoRanks: ReadonlySet<number>,
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "active":
      return r.state !== "declined" && r.state !== "closed";
    case "todo":
      return todoRanks.has(r.rank);
    case "waiting":
      return r.waiting;
    case "contacted":
      return r.contacted;
    case "ended":
      return r.state === "declined" || r.state === "closed";
  }
}
type SortMode = "match" | "intake";
const SORT_STORAGE_KEY = "panel-sort-mode";

export function loadSortMode(): SortMode {
  try {
    return window.localStorage.getItem(SORT_STORAGE_KEY) === "intake"
      ? "intake"
      : "match";
  } catch {
    return "match";
  }
}

export function saveSortMode(mode: SortMode) {
  try {
    window.localStorage.setItem(SORT_STORAGE_KEY, mode);
  } catch {}
}
export function sortRows(rows: TableRow[], mode: SortMode): TableRow[] {
  const ended = (r: TableRow) => r.state === "declined" || r.state === "closed";
  const intakeTs = (r: TableRow) =>
    r.intakeAt ? Date.parse(r.intakeAt) : null;
  return [...rows].sort((a, b) => {
    const ea = ended(a) ? 1 : 0;
    const eb = ended(b) ? 1 : 0;
    if (ea !== eb) return ea - eb;
    if (mode === "match") {
      const sa = a.matchScore;
      const sb = b.matchScore;
      if (sa == null && sb != null) return 1;
      if (sa != null && sb == null) return -1;
      if (sa != null && sb != null && sa !== sb) return sb - sa;
      const ta = intakeTs(a);
      const tb = intakeTs(b);
      if (ta == null && tb != null) return 1;
      if (ta != null && tb == null) return -1;
      if (ta != null && tb != null && ta !== tb) return tb - ta;
      return a.rank - b.rank;
    }
    const ta = intakeTs(a);
    const tb = intakeTs(b);
    if (ta == null && tb != null) return 1;
    if (ta != null && tb == null) return -1;
    if (ta != null && tb != null && ta !== tb) return tb - ta;
    return a.rank - b.rank;
  });
}

export function MuseApp() {
  const api = useMuseActions();
  const policy = useMuseConfiguration();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<MainTab>("progress");
  const [detailSel, setDetailSel] = useState<{
    rank: number;
    view: "detail" | "review";
  } | null>(null);
  const [echo, setEcho] = useState<BatchEcho | null>(null);
  const [watchBatchId, setWatchBatchId] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [todoSel, setTodoSel] = useState<{
    rank: number;
    itemId: string;
  } | null>(null);
  const [jobFilter, setJobFilter] = useState<JobFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>(loadSortMode);

  const snapshotQuery = useQuery({
    queryKey: ["console-snapshot"],
    queryFn: () => api.getConsoleSnapshot({}),
    refetchInterval: policy.refreshMs ?? false,
  });

  const seed = useMutation({
    mutationFn: () => api.seedFromSnapshot({}),
    onSuccess: () => {
      void queryClient.invalidateQueries();
    },
  });

  const sync = useMutation({
    mutationFn: () => api.syncFromHost({}),
    onSuccess: (r) => {
      setNotice(r.message);
      void queryClient.invalidateQueries();
    },
  });

  const makeBatch = useMutation({
    mutationFn: () => api.createExecutionBatch({}),
    onSuccess: (r) => {
      setEcho(r);
      if (r.batchId != null) setWatchBatchId(r.batchId);
      void queryClient.invalidateQueries();
    },
  });

  const confirmExec = useMutation({
    mutationFn: (batchId: number) => api.confirmExecution({ batchId }),
    onSuccess: (r) => {
      setNotice(r.message ?? "执行已启动");
      setEcho(null);
      void queryClient.invalidateQueries();
    },
  });

  const batchStatus = useQuery({
    queryKey: ["batch", watchBatchId],
    queryFn: () => api.getBatch({ batchId: watchBatchId }),
    enabled: watchBatchId > 0,
    refetchInterval: (q) =>
      q.state.data?.batch?.status === "executing"
        ? (policy.batchRefreshMs ?? false)
        : false,
  });

  const snapshot = snapshotQuery.data?.snapshot;
  const seeded = snapshotQuery.data?.seeded ?? false;

  const todosQuery = useQuery({
    queryKey: ["todos"],
    queryFn: () => api.getTodos({}),
    enabled: seeded,
    refetchInterval: policy.refreshMs ?? false,
  });

  const channelLoginQuery = useQuery({
    queryKey: ["channel-login"],
    queryFn: () => api.getChannelLogin({}),
    enabled: seeded,
    refetchInterval: policy.refreshMs ?? false,
  });
  const droppedChannels = (channelLoginQuery.data?.channels ?? []).filter(
    (c) => c.status === "dropped",
  );

  const tableQuery = useQuery({
    queryKey: ["table-data"],
    queryFn: () => api.getTableData({}),
    enabled: seeded,
    refetchInterval: policy.refreshMs ?? false,
  });
  const genProgress = useMutation({
    mutationFn: () =>
      api.generateProgress({
        limit: policy.progressBatchLimit ?? 0,
        force: false,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["table-data"] });
      void queryClient.invalidateQueries({ queryKey: ["job"] });
    },
  });
  const retryProgress = useMutation({
    mutationFn: () =>
      api.generateProgress({
        limit: policy.progressBatchLimit ?? 0,
        force: true,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["table-data"] });
      void queryClient.invalidateQueries({ queryKey: ["job"] });
    },
  });
  const pendingProgress = tableQuery.data?.pendingProgress ?? 0;

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {snapshotQuery.isPending ? (
        <p className="py-16 text-center text-[var(--dim)]">读取队列中…</p>
      ) : !seeded ? (
        <div className="py-16 text-center">
          <p className="text-[var(--dim)]">
            {seed.isPending ? "正在导入宿主队列与历史…" : "尚未导入宿主数据。"}
          </p>
          {!seed.isPending && (
            <button
              type="button"
              className="mt-4 rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2 text-sm text-white"
              onClick={() => seed.mutate()}
            >
              导入队列与历史
            </button>
          )}
        </div>
      ) : snapshot ? (
        <>
          {todoSel && todosQuery.data && (
            <TodoDialog
              key={`${todoSel.rank}-${todoSel.itemId}`}
              rank={todoSel.rank}
              itemId={todoSel.itemId}
              todos={todosQuery.data}
              onClose={() => setTodoSel(null)}
              onMakeBatch={() => makeBatch.mutate()}
              onNotice={setNotice}
            />
          )}

          {detailSel != null && (
            <JobDetailDialog
              key={`${detailSel.rank}-${detailSel.view}`}
              rank={detailSel.rank}
              initialView={detailSel.view}
              onClose={() => setDetailSel(null)}
              onWatchBatch={(id) => setWatchBatchId(id)}
              onOpenTodo={(rank, itemId) => {
                setDetailSel(null);
                setTodoSel({ rank, itemId });
              }}
            />
          )}

          {echo && (
            <EchoPanel
              echo={echo}
              onClose={() => setEcho(null)}
              onConfirm={(id) => confirmExec.mutate(id)}
              confirming={confirmExec.isPending}
            />
          )}

          <div className="mx-auto w-full max-w-[1400px] px-3 pb-12 sm:px-4">
            <nav
              aria-label="面板选项卡"
              role="tablist"
              className="flex flex-wrap gap-x-1 border-b border-[var(--border)]"
            >
              {(
                [
                  ["progress", "任务进度"],
                  ["runs", "运行记录"],
                  ["comms", "沟通进展"],
                  ["about", "数据说明"],
                ] as [MainTab, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  aria-label={`切换到${label}`}
                  className={`-mb-px border-b-2 px-3 py-2.5 text-[15px] ${
                    tab === key
                      ? "border-[var(--accent)] font-semibold text-[var(--accent)]"
                      : "border-transparent text-[var(--dim)] hover:text-[var(--text)]"
                  }`}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </nav>

            {tab === "progress" && (
              <>
                {(() => {
                  const allRows = tableQuery.data?.rows ?? [];
                  const todoRanks = new Set(
                    (todosQuery.data?.jobs ?? []).map((j) => j.rank),
                  );
                  const countFor = (f: JobFilter) =>
                    allRows.filter((r) => rowMatchesFilter(r, f, todoRanks))
                      .length;
                  const toggleFilter = (f: JobFilter) =>
                    setJobFilter((prev) => (prev === f ? "all" : f));
                  const tabCls = (f: JobFilter) =>
                    `relative -mb-px border-b-2 py-2.5 pl-3 pr-8 text-[15px] ${
                      jobFilter === f
                        ? "border-[var(--accent)] font-semibold text-[var(--accent)]"
                        : "border-transparent text-[var(--dim)] hover:text-[var(--text)]"
                    }`;
                  const sortBtnCls = (mode: SortMode) =>
                    `rounded-[var(--radius)] border px-2.5 py-1 text-[13px] ${
                      sortMode === mode
                        ? "border-[var(--accent)] bg-[var(--accent-soft)] font-semibold text-[var(--accent)]"
                        : "border-[var(--border)] bg-[var(--surface)] text-[var(--text)] hover:bg-[#f7fafd]"
                    }`;
                  return (
                    <>
                      {droppedChannels.length > 0 && (
                        <div
                          className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--warn-soft)] px-3 py-2"
                          role="status"
                          aria-label="渠道登录状态"
                        >
                          {droppedChannels.map((c) => (
                            <LoginRestoreEntry key={c.channel} channel={c} />
                          ))}
                        </div>
                      )}
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-4">
                        <h1 className="text-xl font-semibold">岗位进展</h1>
                        <div className="ml-auto flex flex-wrap items-center gap-2">
                          <div
                            className="flex items-center gap-2"
                            role="group"
                            aria-label="排序方式"
                          >
                            {(
                              [
                                ["match", "按匹配度"],
                                ["intake", "按入库时间"],
                              ] as [SortMode, string][]
                            ).map(([mode, label]) => (
                              <button
                                key={mode}
                                type="button"
                                aria-label={label}
                                aria-pressed={sortMode === mode}
                                className={sortBtnCls(mode)}
                                onClick={() => {
                                  setSortMode(mode);
                                  saveSortMode(mode);
                                }}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                          <button
                            type="button"
                            aria-label="从宿主队列刷新"
                            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-sm"
                            disabled={sync.isPending}
                            onClick={() => sync.mutate()}
                          >
                            {sync.isPending ? "刷新中…" : "刷新"}
                          </button>
                          <button
                            type="button"
                            aria-label="生成执行清单"
                            className="rounded-[var(--radius)] bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white"
                            disabled={makeBatch.isPending}
                            onClick={() => makeBatch.mutate()}
                          >
                            {makeBatch.isPending ? "生成中…" : "执行清单"}
                          </button>
                        </div>
                      </div>

                      <div
                        className="flex flex-wrap gap-x-1 border-b border-[var(--border)]"
                        role="tablist"
                        aria-label="岗位筛选"
                      >
                        <button
                          type="button"
                          role="tab"
                          aria-selected={jobFilter === "all"}
                          aria-label={`全部，${countFor("all")} 个岗位`}
                          className={tabCls("all")}
                          onClick={() => setJobFilter("all")}
                        >
                          全部
                          <span className="absolute right-1.5 top-1.5 text-xs font-semibold text-[var(--dim)]">
                            {countFor("all")}
                          </span>
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={jobFilter === "active"}
                          aria-label={`正在推进，${countFor("active")} 个岗位`}
                          className={tabCls("active")}
                          onClick={() => toggleFilter("active")}
                        >
                          正在推进
                          <span className="absolute right-1.5 top-1.5 text-xs font-semibold text-[var(--accent)]">
                            {countFor("active")}
                          </span>
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={jobFilter === "todo"}
                          aria-label={`等你处理，${countFor("todo")} 个岗位`}
                          className={tabCls("todo")}
                          onClick={() => toggleFilter("todo")}
                        >
                          等你处理
                          <span className="absolute right-1 top-1.5 inline-flex items-center gap-1">
                            <span
                              aria-hidden="true"
                              className="h-2 w-2 rounded-full"
                              style={{ background: "#c62f24" }}
                            />
                            <span
                              className="text-xs font-semibold"
                              style={{ color: "#c62f24" }}
                            >
                              {countFor("todo")}
                            </span>
                          </span>
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={jobFilter === "waiting"}
                          aria-label={`等待对方，${countFor("waiting")} 个岗位`}
                          className={tabCls("waiting")}
                          onClick={() => toggleFilter("waiting")}
                        >
                          等待对方
                          <span className="absolute right-1.5 top-1.5 text-xs font-semibold text-[var(--accent)]">
                            {countFor("waiting")}
                          </span>
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={jobFilter === "ended"}
                          aria-label={`已结束，${countFor("ended")} 个岗位`}
                          className={tabCls("ended")}
                          onClick={() => toggleFilter("ended")}
                        >
                          已结束
                          <span className="absolute right-1.5 top-1.5 text-xs font-semibold text-[var(--dim)]">
                            {countFor("ended")}
                          </span>
                        </button>
                      </div>

                      <FiveColumnTable
                        rows={sortRows(
                          allRows.filter((r) =>
                            rowMatchesFilter(r, jobFilter, todoRanks),
                          ),
                          sortMode,
                        )}
                        filterActive={jobFilter !== "all"}
                        todos={todosQuery.data ?? null}
                        loading={tableQuery.isPending}
                        pendingProgress={pendingProgress}
                        failedProgress={tableQuery.data?.failedProgress ?? 0}
                        onRetryFailed={() => retryProgress.mutate()}
                        retrying={retryProgress.isPending}
                        onOpenDetail={(rank) =>
                          setDetailSel({ rank, view: "detail" })
                        }
                        onOpenReview={(rank) =>
                          setDetailSel({ rank, view: "review" })
                        }
                        onOpenTodo={(rank, itemId) =>
                          setTodoSel({ rank, itemId })
                        }
                      />
                    </>
                  );
                })()}

                <section aria-label="决定与执行" className="pt-2">
                  <p className="text-[13px] text-[var(--dim)]">
                    发送与投递在执行清单里确认。
                  </p>
                  {notice && (
                    <p
                      className="mt-2 text-sm text-[var(--accent)]"
                      role="status"
                    >
                      {notice}
                    </p>
                  )}

                  {batchStatus.data?.batch?.status === "executing" && (
                    <section
                      aria-label="执行进度"
                      className="mt-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--warn-soft)] p-3"
                    >
                      <h3 className="text-sm font-semibold">
                        第 {batchStatus.data.batch.id} 批执行中，逐条回读中…
                      </h3>
                      <ul className="mt-2 space-y-1 text-sm">
                        {batchStatus.data.items.map((it) => (
                          <li key={it.rank} className="flex gap-2">
                            <span className="font-mono text-[var(--dim)]">
                              #{it.rank}
                            </span>
                            <span className="flex-1">
                              {it.company} · {it.title}
                            </span>
                            <span>
                              {it.status === "done"
                                ? "✓ 已完成"
                                : it.status === "failed"
                                  ? `✗ ${it.detail ?? "失败"}`
                                  : "…执行中"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  <p className="mt-4 text-sm text-[var(--dim)]">
                    点一行里的任意位置打开这个岗位的详情。
                  </p>

                  <section aria-label="更多" className="mt-6">
                    <details className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-3">
                      <summary className="cursor-pointer text-sm font-semibold">
                        更多
                      </summary>
                      <details className="mt-2 rounded-[var(--radius)] border border-[var(--border)] p-3">
                        <summary className="cursor-pointer text-sm font-semibold">
                          排查问题
                        </summary>
                        <p className="mt-2 text-sm text-[var(--dim)]">
                          供排查问题时查看的数据来源与原始记录。原始字段没有删除，只是收在这里，不在日常视图里默认展示。
                        </p>
                        <h4 className="mt-3 text-sm font-semibold">数据来源</h4>
                        <ul className="mt-1 space-y-1 text-sm">
                          {snapshot.sources.map((s) => (
                            <li key={s.name} className="flex flex-wrap gap-x-2">
                              <strong className="font-medium">{s.name}</strong>
                              <span className="text-[var(--dim)]">
                                {s.status}
                              </span>
                              {s.message && <span>{s.message}</span>}
                            </li>
                          ))}
                        </ul>
                        <details className="mt-3">
                          <summary className="cursor-pointer text-sm">
                            查看本页完整数据（JSON）
                          </summary>
                          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius)] border border-[var(--border)] p-2 text-xs">
                            {JSON.stringify(snapshot, null, 2)}
                          </pre>
                        </details>
                      </details>
                    </details>
                  </section>
                </section>
              </>
            )}

            {tab === "runs" && <RunsPanel snapshot={snapshot} />}

            {tab === "comms" && (
              <CommsPanel
                snapshot={snapshot}
                onOpenDetail={(rank) => setDetailSel({ rank, view: "detail" })}
              />
            )}

            {tab === "about" && (
              <AboutPanel
                snapshot={snapshot}
                hardCounts={snapshotQuery.data?.hardCounts ?? {}}
                matchCount={snapshotQuery.data?.matchCount ?? 0}
                todoJobs={todosQuery.data?.jobCount ?? 0}
                todoItems={todosQuery.data?.itemCount ?? 0}
              />
            )}
          </div>
        </>
      ) : (
        <p className="py-16 text-center text-[var(--dim)]">
          快照读取失败，请点「导入队列与历史」或稍后重试。
        </p>
      )}
    </div>
  );
}

type TableRow = ApiResponse<typeof api, "getTableData">["rows"][number];
function FiveColumnTable({
  rows,
  todos,
  loading,
  pendingProgress,
  failedProgress,
  onRetryFailed,
  retrying,
  onOpenDetail,
  onOpenReview,
  onOpenTodo,
  filterActive,
}: {
  rows: TableRow[];
  todos: TodosResp | null;
  loading: boolean;
  pendingProgress: number;
  failedProgress: number;
  onRetryFailed: () => void;
  retrying: boolean;
  onOpenDetail: (rank: number) => void;
  onOpenReview: (rank: number) => void;
  onOpenTodo: (rank: number, itemId: string) => void;
  filterActive: boolean;
}) {
  const todoByRank = new Map<number, TodoJob>();
  for (const j of todos?.jobs ?? []) todoByRank.set(j.rank, j);
  const cols =
    "md:grid-cols-[minmax(190px,1.25fr)_68px_minmax(230px,1.2fr)_minmax(250px,1.55fr)_minmax(150px,0.8fr)]";
  return (
    <section aria-label="岗位列表" className="w-full pt-4">
      {pendingProgress > 0 && (
        <p className="pb-2 text-xs text-[var(--dim)]" role="status">
          进展正在逐岗更新，还剩 {pendingProgress}{" "}
          个；没更新到的先显示上次的进展或稍后再看。
        </p>
      )}
      {failedProgress > 0 && (
        <p
          className="flex flex-wrap items-center gap-2 pb-2 text-xs text-[var(--warn)]"
          role="status"
        >
          <span>
            有 {failedProgress}{" "}
            个岗位的进展几次都没生成出来，原因写在各自那一行里。
          </span>
          <button
            type="button"
            aria-label="重新生成失败的进展"
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--text)]"
            disabled={retrying}
            onClick={onRetryFailed}
          >
            {retrying ? "正在重新生成…" : "重新生成"}
          </button>
        </p>
      )}
      <div className="rounded-[10px] border border-[var(--border)] bg-[var(--surface)] shadow-[0_1px_3px_rgba(38,49,67,0.06)]">
        <div
          className={`hidden gap-3 border-b border-[var(--border)] px-4 pb-2 pt-3 text-xs font-semibold text-[var(--dim)] md:grid ${cols}`}
          aria-hidden="true"
        >
          <span>岗位</span>
          <span>渠道</span>
          <span>匹配情况</span>
          <span>进展</span>
          <span>待你处理</span>
        </div>
        {loading && rows.length === 0 ? (
          <p className="py-10 text-center text-sm text-[var(--dim)]">
            读取岗位中…
          </p>
        ) : rows.length === 0 ? (
          <p className="py-10 text-center text-sm text-[var(--dim)]">
            {filterActive ? "这一类暂时没有岗位。" : "暂时没有岗位。"}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {rows.map((r) => {
              const todo = todoByRank.get(r.rank);
              return (
                <li
                  key={r.rank}
                  className={`grid cursor-pointer grid-cols-1 gap-x-3 gap-y-1.5 px-4 py-3.5 hover:bg-[#f7fafd] md:items-start ${cols}`}
                  onClick={() => {
                    const sel = window.getSelection();
                    if (sel && sel.toString().length > 0) return;
                    onOpenDetail(r.rank);
                  }}
                >
                  <div className="min-w-0">
                    <button
                      type="button"
                      aria-label={`打开岗位详情：${r.title}，${displayCompany(r.company)}`}
                      className="text-left text-[15px] font-medium leading-snug text-[var(--text)] underline-offset-2 hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenDetail(r.rank);
                      }}
                    >
                      {r.title}
                    </button>
                    <p className="mt-0.5 text-sm text-[var(--dim)]">
                      {displayCompany(r.company)}
                    </p>
                  </div>
                  <div>
                    <span className="mb-0.5 block text-xs font-semibold text-[var(--dim)] md:hidden">
                      渠道
                    </span>
                    <button
                      type="button"
                      aria-label={`${r.channel}渠道详情：${r.title}`}
                      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenDetail(r.rank);
                      }}
                    >
                      {r.channel}
                    </button>
                  </div>
                  <div className="text-sm leading-snug">
                    <span className="mb-0.5 block text-xs font-semibold text-[var(--dim)] md:hidden">
                      匹配情况
                    </span>
                    <ul className="space-y-1">
                      {r.matchBullets.map((b, i) => (
                        <li key={i} className="flex gap-1.5">
                          <span
                            aria-hidden="true"
                            className="mt-[8px] h-1 w-1 flex-none rounded-full bg-[var(--dim)]"
                          />
                          <span>{b}</span>
                        </li>
                      ))}
                    </ul>
                    {r.matchScore != null &&
                      Math.round(r.matchScore * 100) < 100 && (
                        <p className="mt-1 text-xs text-[var(--dim)]">
                          要点匹配 {Math.round(r.matchScore * 100)} 分，仅作参考
                        </p>
                      )}
                  </div>
                  <div className="text-sm leading-relaxed">
                    <span className="mb-0.5 block text-xs font-semibold text-[var(--dim)] md:hidden">
                      进展
                    </span>
                    {r.progress ? (
                      <p>
                        {r.progress}
                        {r.progressStale && (
                          <span className="ml-1 text-xs text-[var(--warn)]">
                            （可能不是最新情况）
                          </span>
                        )}
                      </p>
                    ) : r.progressError ? (
                      <p className="text-[var(--warn)]">
                        进展没生成出来：{r.progressError}。
                      </p>
                    ) : (
                      <p className="text-[var(--dim)]">
                        进展暂时没更新，稍后再看。
                      </p>
                    )}
                  </div>
                  <div>
                    <span className="mb-0.5 block text-xs font-semibold text-[var(--dim)] md:hidden">
                      待你处理
                    </span>
                    {todo && todo.items.length > 0 ? (
                      <div className="flex flex-col items-start gap-1.5">
                        {todo.items.map((it) => (
                          <button
                            key={it.id}
                            type="button"
                            aria-label={`${r.title}，${displayCompany(r.company)}：${it.action}`}
                            className="inline-flex min-h-[36px] items-center gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 text-left text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (it.kind === "greeting") onOpenReview(r.rank);
                              else onOpenTodo(r.rank, it.id);
                            }}
                          >
                            <span
                              aria-hidden="true"
                              className="h-2.5 w-2.5 flex-none rounded-full"
                              style={{ background: "#c62f24" }}
                            />
                            {it.action}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

type TodoJob = TodosResp["jobs"][number];
type TodoItem = TodoJob["items"][number];

type SnapshotData = ApiResponse<typeof api, "getConsoleSnapshot">["snapshot"];

const ACTIVITY_LABELS: Record<string, string> = {
  match: "评估匹配度",
  draft_greeting: "写招呼语",
  approval: "记录决定",
  readback: "投递结果读回",
  review: "已发情况检查",
};

export function fmtRunTime(iso: unknown): string {
  if (typeof iso !== "string") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const panelShell =
  "rounded-[10px] border border-[var(--border)] bg-[var(--surface)] shadow-[0_1px_3px_rgba(38,49,67,0.06)]";
function RunsPanel({ snapshot }: { snapshot: SnapshotData }) {
  const jobById = new Map<string, Record<string, unknown>>();
  for (const j of snapshot.jobs) {
    jobById.set(String(j.job["job_id"] ?? ""), j.job);
  }
  const runs = [...snapshot.runs].sort((a, b) =>
    String(b.run["created_at"] ?? "").localeCompare(
      String(a.run["created_at"] ?? ""),
    ),
  );
  const totalActs = runs.reduce((n, r) => n + r.activities.length, 0);
  return (
    <section aria-label="运行记录" className="pt-4">
      <div className={panelShell}>
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-base font-semibold">运行记录</h2>
          <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--dim)]">
            共 {runs.length} 批、{totalActs}{" "}
            条已经完成的工作，按记录时间从新到旧排。没有保存时间的记录不在这里推算时间，可以在岗位详情的历史里看。
          </p>
        </div>
        {runs.length === 0 ? (
          <p className="px-4 py-8 text-sm text-[var(--dim)]">
            还没有带时间的运行记录。
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {runs.map((r, ri) => (
              <li key={ri} className="px-4 py-3">
                <p className="text-sm font-medium">
                  {fmtRunTime(r.run["created_at"])}
                  <span className="text-[var(--dim)]">
                    {" · "}
                    {ACTIVITY_LABELS[
                      String(r.activities[0]?.["activity"] ?? "")
                    ] ?? "已完成的工作"}
                    {" · "}
                    {r.activities.length} 个岗位
                  </span>
                </p>
                <ul className="mt-1.5 space-y-1.5">
                  {r.activities.map((a, ai) => {
                    const job = jobById.get(String(a["job_id"] ?? ""));
                    return (
                      <li key={ai} className="text-sm leading-relaxed">
                        <span className="font-medium">
                          {String(job?.["title"] ?? a["job_id"] ?? "")}
                        </span>
                        {job?.["company"] ? (
                          <span className="text-[var(--dim)]">
                            {" "}
                            · {String(job["company"])}
                          </span>
                        ) : null}
                        {a["message"] ? (
                          <span className="block text-[var(--dim)]">
                            {String(a["message"])}
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
function CommsPanel({
  snapshot,
  onOpenDetail,
}: {
  snapshot: SnapshotData;
  onOpenDetail: (rank: number) => void;
}) {
  const sent = snapshot.jobs.filter((j) => j.job["send_status"] === "sent");
  const delivered = snapshot.jobs.filter(
    (j) => j.job["delivery_status"] === "delivered",
  );
  const already = snapshot.jobs.filter(
    (j) => j.job["delivery_status"] === "already_delivered_before_muse",
  );
  const groups: {
    heading: string;
    jobs: typeof sent;
    note: (job: (typeof sent)[number]) => string;
  }[] = [
    {
      heading: "招呼语已发出",
      jobs: sent,
      note: () => "已有发送读回记录。",
    },
    {
      heading: "简历已投递并核实",
      jobs: delivered,
      note: (job) =>
        job.job["delivery_result"]
          ? `投递结果：${String(job.job["delivery_result"])}`
          : "投递已经核实。",
    },
    {
      heading: "接手之前就投递过",
      jobs: already,
      note: () => "记录显示这个岗位在面板接手之前已经投递过，不是这次新投的。",
    },
  ];
  const total = sent.length + delivered.length + already.length;
  return (
    <section aria-label="沟通进展" className="pt-4">
      <div className={panelShell}>
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-base font-semibold">沟通进展</h2>
          <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--dim)]">
            这里只列已经核实的联系：发出过的招呼语和投递过的简历。本地没有保存双方消息原文，所以对方有没有回复，在没有核实之前不会写成结论。
          </p>
        </div>
        {total === 0 ? (
          <p className="px-4 py-8 text-sm text-[var(--dim)]">
            暂时没有已核实的联系记录。
          </p>
        ) : (
          groups
            .filter((g) => g.jobs.length > 0)
            .map((g) => (
              <div
                key={g.heading}
                className="border-b border-[var(--border)] px-4 py-3 last:border-b-0"
              >
                <h3 className="text-sm font-semibold">
                  {g.heading}
                  <span className="ml-2 text-[13px] font-normal text-[var(--dim)]">
                    {g.jobs.length} 个岗位
                  </span>
                </h3>
                <ul className="mt-2 space-y-2">
                  {g.jobs.map((j) => {
                    const rank = Number(j.job["host_rank"]);
                    return (
                      <li
                        key={rank}
                        className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm"
                      >
                        <button
                          type="button"
                          aria-label={`打开岗位详情：${String(j.job["title"] ?? "")}，${String(j.job["company"] ?? "")}`}
                          className="font-medium underline-offset-2 hover:underline"
                          onClick={() => onOpenDetail(rank)}
                        >
                          {String(j.job["title"] ?? "")}
                        </button>
                        <span className="text-[var(--dim)]">
                          {displayCompany(String(j.job["company"] ?? ""))}
                        </span>
                        <span className="text-[var(--dim)]">{g.note(j)}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
        )}
      </div>
    </section>
  );
}
function AboutPanel({
  snapshot,
  hardCounts,
  matchCount,
  todoJobs,
  todoItems,
}: {
  snapshot: SnapshotData;
  hardCounts: Record<string, number>;
  matchCount: number;
  todoJobs: number;
  todoItems: number;
}) {
  const total = snapshot.jobs.length;
  const statusOf = (s: string) =>
    snapshot.jobs.filter((j) => j.job["host_status"] === s).length;
  const sections: { heading: string; lines: string[] }[] = [
    {
      heading: "岗位与状态",
      lines: [
        `这一页共有 ${total} 个岗位，来自你的求职队列：待审阅 ${statusOf("pending_review")} 个、已批准待执行 ${statusOf("approved_pending_execution")} 个、已投递 ${statusOf("delivered")} 个、已拒绝 ${statusOf("declined")} 个。`,
        "点右上角「刷新」会重新读取队列；你在面板里做的决定会保存下来，刷新、关闭再打开都不会丢。",
      ],
    },
    {
      heading: "匹配情况怎么看",
      lines: [
        `匹配情况是把每个岗位的职位要点和你的工作记录逐条核对后的结论，已经评估 ${matchCount} 个岗位。基本要求核对：符合 ${hardCounts["PASS"] ?? 0} 个、有一项待确认 ${hardCounts["REVIEW"] ?? 0} 个、不符合 ${hardCounts["REJECT"] ?? 0} 个。`,
        "列表里分点写的是核对结果、对得上的经历和待确认项；分数只是次要参考，判断以文字结论为准。详细依据在岗位详情里。",
      ],
    },
    {
      heading: "进展是怎么来的",
      lines: [
        "每段进展根据这个岗位已经保存的记录自动整理，只说明目前进展，长度控制在几十字内；记录有变化时会重新整理。进展只是说明，不是发送或批准的凭证。",
      ],
    },
    {
      heading: "红点是什么意思",
      lines: [
        `红点只表示需要你本人决定的事，现在有 ${todoJobs} 个岗位、共 ${todoItems} 件事。看过或关掉弹窗不会让红点消失，处理并保存成功后才会更新。`,
        "还没有招呼语草稿的待审岗位属于待核查、待起稿的工作，不算你的待办，也不会标红点。",
      ],
    },
    {
      heading: "还缺的记录",
      lines: [
        "本地没有保存双方消息原文，所以对方的回复情况在核实之前不会写成结论；沟通进展里只列已经核实的发出和投递。",
        "职位说明只有要点摘要，没有保存全文；少数旧记录没有保存时间，详情里会注明时间未保存。",
      ],
    },
  ];
  return (
    <section aria-label="数据说明" className="pt-4">
      <div className={panelShell}>
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-base font-semibold">数据说明</h2>
        </div>
        {sections.map((s) => (
          <div
            key={s.heading}
            className="border-b border-[var(--border)] px-4 py-3 last:border-b-0"
          >
            <h3 className="text-sm font-semibold">{s.heading}</h3>
            {s.lines.map((line, i) => (
              <p
                key={i}
                className="mt-1 text-sm leading-relaxed text-[var(--dim)]"
              >
                {line}
              </p>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
type DecisionKindArg =
  | "accept_original"
  | "accept_revise"
  | "decline"
  | "deliver"
  | "skip"
  | "close"
  | "reopen"
  | "resolve_block"
  | "approve_text";

function TodoDialog({
  rank,
  itemId,
  todos,
  onClose,
  onMakeBatch,
  onNotice,
}: {
  rank: number;
  itemId: string;
  todos: TodosResp;
  onClose: () => void;
  onMakeBatch: () => void;
  onNotice: (msg: string) => void;
}) {
  const api = useMuseActions();
  const policy = useMuseConfiguration();
  const queryClient = useQueryClient();
  const [frozen] = useState<TodoJob | null>(
    () => todos.jobs.find((j) => j.rank === rank) ?? null,
  );
  const [currentId, setCurrentId] = useState(itemId);
  const [greetingText, setGreetingText] = useState<string | null>(null);
  const [phase, setPhase] = useState<
    "idle" | "saving" | "saved" | "failed" | "unknown"
  >("idle");
  const [savedText, setSavedText] = useState("");
  const [remaining, setRemaining] = useState<TodoItem[]>([]);
  const detail = useQuery({
    queryKey: ["job", rank],
    queryFn: () => api.getJob({ rank }),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!frozen) return null;
  const item =
    frozen.items.find((i) => i.id === currentId) ?? frozen.items[0] ?? null;
  if (!item) return null;
  const d = detail.data;
  const greetingValue =
    greetingText ?? d?.approvedGreeting ?? d?.draftGreeting ?? "";
  const isLiepin = frozen.platform === "猎聘";
  const saving = phase === "saving";

  async function decide(
    kind: DecisionKindArg,
    opts: {
      note?: string | null;
      greetingText?: string | null;
      resultText: string;
    },
  ) {
    setPhase("saving");
    try {
      const r = await api.recordDecision({
        rank,
        kind,
        note: opts.note ?? null,
        greetingText: opts.greetingText ?? null,
      });
      if (!r.ok) {
        setPhase("failed");
        return;
      }
      const fresh = await queryClient.fetchQuery({
        queryKey: ["job", rank],
        queryFn: () => api.getJob({ rank }),
      });
      const found = fresh.decisions.some((dec) => dec.id === r.decisionId);
      if (!found) {
        setPhase("unknown");
        void queryClient.invalidateQueries();
        return;
      }
      const freshTodos = await api.getTodos({});
      queryClient.setQueryData(["todos"], freshTodos);
      void queryClient.invalidateQueries({ queryKey: ["console-snapshot"] });
      setRemaining(freshTodos.jobs.find((j) => j.rank === rank)?.items ?? []);
      setSavedText(opts.resultText);
      setPhase("saved");
    } catch {
      setPhase("failed");
    }
  }

  const reasonsJoined = item.reasons.join("；");
  const promptText =
    item.kind === "block"
      ? item.action === "看看屏蔽问题"
        ? "这个岗位被屏蔽挡住了，怎么处理由你判定。"
        : "这个岗位与另一个岗位重复，保留哪个由你判定。"
      : item.question;

  const choices: {
    label: string;
    caption: string;
    run: () => void;
    primary?: boolean;
  }[] =
    item.kind === "greeting"
      ? [
          {
            label: "这版文案可以",
            caption: "只记下你对这版文案的意见，不批准发送，也不会发送。",
            primary: true,
            run: () =>
              void decide("approve_text", {
                resultText:
                  "记下了：这版文案可以。这只是文案意见，还没有批准发送。",
              }),
          },
          {
            label: "批准这份材料",
            caption:
              "批准的就是上面这份准确全文；交由既有审批流程核验，不自动发送，发送前还要逐条确认。",
            run: () =>
              void decide("accept_original", {
                greetingText,
                resultText:
                  "这份材料已批准。还没有发送；发送前还要在执行清单里逐条核对确认。",
              }),
          },
          {
            label: "帮我改一下",
            caption:
              "提交修改意见并准备新稿，旧稿保留；新稿保存后回到这里查看。",
            run: () =>
              void decide("accept_revise", {
                resultText:
                  "记下了：招呼语要改。改好后会再给你看，你确认后才谈发送。",
              }),
          },
          {
            label: "先放一放",
            caption: "保存暂缓决定，不永久关闭，以后还可以继续。",
            run: () =>
              void decide("skip", {
                resultText: "这个岗位先放一放，以后还可以继续。",
              }),
          },
          {
            label: "放弃这个岗位",
            caption: "记下决定，这个岗位不再考虑、不再推进。",
            run: () =>
              void decide("decline", {
                resultText: "这个岗位已放弃，不再推进。",
              }),
          },
        ]
      : item.kind === "review"
        ? [
            {
              label: "这个条件可以接受，继续了解",
              caption:
                "只记下你的确认，这个岗位继续推进；不会发消息，也不会投递。",
              primary: true,
              run: () =>
                void decide("reopen", {
                  note: `基本要求：已确认可接受（${reasonsJoined}）`,
                  resultText: "继续了解这个岗位。",
                }),
            },
            {
              label: "先放一放",
              caption: "暂时不推进，以后还可以继续，不会关闭这个岗位。",
              run: () =>
                void decide("skip", {
                  note: `基本要求：先放一放（${reasonsJoined}）`,
                  resultText: "这个岗位先放一放，以后还可以继续。",
                }),
            },
            {
              label: "这个条件不合适",
              caption: "记下决定，这个岗位不再推进。",
              run: () =>
                void decide("decline", {
                  note: `基本要求：条件不合适（${reasonsJoined}）`,
                  resultText: "这个条件不合适，这个岗位不再推进。",
                }),
            },
          ]
        : item.kind === "block"
          ? [
              {
                label: "我已判定，解除阻塞",
                caption:
                  "只记下你的判定；面板不会自动解屏蔽，也不会合并重复岗位。",
                primary: true,
                run: () =>
                  void decide("resolve_block", {
                    resultText:
                      "阻塞已按你的判定解除。这个岗位接下来是否推进，按它的其他事项继续处理。",
                  }),
              },
            ]
          : [
              {
                label: "生成执行清单",
                caption:
                  "清单会列出全部待执行岗位；你逐条核对后再点确认执行，才会真正" +
                  (isLiepin ? "投递。" : "发送。"),
                primary: true,
                run: () => {
                  onMakeBatch();
                  onNotice(
                    "执行清单已生成，请在弹窗里逐条核对全文后再确认执行。",
                  );
                  onClose();
                },
              },
            ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/35 sm:items-center sm:p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${frozen.title}，${frozen.company}：${item.action}`}
        className="max-h-[92vh] w-full max-w-[560px] overflow-y-auto rounded-t-[var(--radius)] bg-[var(--surface)] p-4 text-[var(--text)] sm:rounded-[var(--radius)]"
      >
        <div className="flex items-start gap-2">
          <span
            aria-hidden="true"
            className="mt-1.5 h-2.5 w-2.5 flex-none rounded-full"
            style={{ background: "#c62f24" }}
          />
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold leading-snug">
              {item.action} · {frozen.title}
            </h3>
            <p className="text-sm text-[var(--dim)]">
              {displayCompany(frozen.company)} · {frozen.platform}
              {frozen.location ? ` · ${frozen.location}` : ""}
              {frozen.salary ? (
                <>
                  {" · "}
                  <strong className="font-semibold text-[var(--text)]">
                    {frozen.salary}
                  </strong>
                </>
              ) : (
                ""
              )}
            </p>
          </div>
          <button
            type="button"
            aria-label="关闭（先不决定）"
            className="flex-none rounded-[var(--radius)] border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50"
            disabled={saving}
            onClick={onClose}
          >
            关闭
          </button>
        </div>

        {phase === "saved" ? (
          <div className="mt-4">
            <p className="text-base font-semibold">记下了。</p>
            <p className="mt-1 text-sm">{savedText}</p>
            {remaining.length > 0 ? (
              <>
                <p className="mt-2 text-sm">
                  这件事记下了，还有 {remaining.length} 件需要你看看。
                </p>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    className="flex-1 rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white"
                    onClick={() => {
                      const next = remaining[0];
                      if (next) {
                        setCurrentId(next.id);
                        setGreetingText(null);
                        setPhase("idle");
                      }
                    }}
                  >
                    看看下一件：{remaining[0]?.action}
                  </button>
                  <button
                    type="button"
                    className="rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
                    onClick={onClose}
                  >
                    关闭
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="mt-2 text-sm text-[var(--dim)]">
                  这个岗位暂时没有需要你处理的事了。
                </p>
                <button
                  type="button"
                  className="mt-3 w-full rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
                  onClick={onClose}
                >
                  关闭
                </button>
              </>
            )}
          </div>
        ) : phase === "unknown" ? (
          <div className="mt-4">
            <p className="text-sm text-[var(--danger)]" role="alert">
              还不能确定有没有保存成功，先别重复提交。
            </p>
            <p className="mt-1 text-sm text-[var(--dim)]">
              关掉后重新打开这个岗位，看决定记录里有没有刚才的选择；没有再重新决定。
            </p>
            <button
              type="button"
              className="mt-3 w-full rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
              onClick={onClose}
            >
              关闭
            </button>
          </div>
        ) : (
          <>
            <h4 className="mt-4 text-sm font-semibold">请你决定</h4>
            <p className="mt-1 text-base font-medium leading-snug">
              {promptText}
            </p>

            {item.kind === "greeting" && (
              <div className="mt-3">
                <p className="text-sm text-[var(--dim)]">
                  招呼语写好了，还没有发送。
                </p>
                {d && d.jdPoints.length > 0 && (
                  <>
                    <h5 className="mt-3 text-sm font-semibold">岗位要点</h5>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                      {d.jdPoints.slice(0, 3).map((p, i) => (
                        <li key={i}>{p}</li>
                      ))}
                    </ul>
                  </>
                )}
                <div className="mt-3 flex items-center gap-2">
                  <h5 className="text-sm font-semibold">招呼语</h5>
                  <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
                    拟发送
                  </span>
                </div>
                <textarea
                  aria-label="招呼语（拟发送，可编辑）"
                  className="mt-2 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-2 text-sm leading-relaxed focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
                  rows={7}
                  value={greetingValue}
                  disabled={saving || detail.isPending}
                  onChange={(e) => setGreetingText(e.target.value)}
                />
              </div>
            )}

            {item.kind === "review" && (
              <div className="mt-3">
                <h5 className="text-sm font-semibold">为什么问你</h5>
                {item.reasons.map((r, i) => (
                  <blockquote
                    key={i}
                    className="mt-2 rounded-[var(--radius)] border border-[var(--border)] p-2 text-sm"
                  >
                    {r}
                  </blockquote>
                ))}
                {frozen.matchStrengths.length > 0 && (
                  <p className="mt-3 text-sm">
                    你的经历里比较接近的部分：
                    {frozen.matchStrengths.join("；")}
                  </p>
                )}
                {frozen.matchPartial.length > 0 && (
                  <p className="mt-1 text-sm">
                    部分接近：{frozen.matchPartial.join("；")}
                  </p>
                )}
                {frozen.matchUncertainties.length > 0 && (
                  <p className="mt-1 text-sm">
                    还没核实的部分：{frozen.matchUncertainties.join("；")}
                  </p>
                )}
                {frozen.matchOverall != null && (
                  <p className="mt-2 text-xs text-[var(--dim)]">
                    匹配度 {Math.round(frozen.matchOverall * 100)}
                    ：表示岗位要点与你的经历有多接近，不是录用概率。
                  </p>
                )}
              </div>
            )}

            {item.kind === "block" && (
              <div className="mt-3">
                <h5 className="text-sm font-semibold">记录里写的是</h5>
                <blockquote className="mt-2 rounded-[var(--radius)] border border-[var(--border)] p-2 text-sm">
                  {item.question}
                </blockquote>
                <p className="mt-2 text-sm text-[var(--dim)]">
                  判定前，这个岗位不会进入执行清单。
                </p>
              </div>
            )}

            {item.kind === "execution" && (
              <div className="mt-3">
                {isLiepin ? (
                  <p className="text-sm">
                    投递用的是统一在线简历。这个岗位已经确认要投，还没有执行投递。
                  </p>
                ) : (
                  <>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold">招呼语</p>
                      <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
                        拟发送
                      </span>
                    </div>
                    <p className="mt-2 whitespace-pre-wrap rounded-[var(--radius)] border border-[var(--border)] p-2 text-sm leading-relaxed">
                      {greetingValue || "还没有保存招呼语全文。"}
                    </p>
                  </>
                )}
              </div>
            )}

            {phase === "failed" && (
              <p className="mt-3 text-sm text-[var(--danger)]" role="alert">
                没有保存成功，你刚才的选择还没生效。
              </p>
            )}
            {saving && (
              <p className="mt-3 text-sm text-[var(--dim)]" role="status">
                正在保存……
              </p>
            )}

            <div className="mt-4 space-y-2">
              {choices.map((c) => (
                <button
                  key={c.label}
                  type="button"
                  aria-label={c.label}
                  disabled={saving}
                  onClick={c.run}
                  className={
                    c.primary
                      ? "w-full rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2.5 text-left text-white disabled:opacity-50"
                      : "w-full rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-left disabled:opacity-50"
                  }
                >
                  <span className="block text-sm font-semibold">{c.label}</span>
                  <span
                    className={
                      c.primary
                        ? "mt-0.5 block text-xs text-white/85"
                        : "mt-0.5 block text-xs text-[var(--dim)]"
                    }
                  >
                    {c.caption}
                  </span>
                </button>
              ))}
              <button
                type="button"
                className="w-full rounded-[var(--radius)] px-4 py-2 text-sm text-[var(--dim)] disabled:opacity-50"
                disabled={saving}
                onClick={onClose}
              >
                先不决定，关闭（这件事会保留）
              </button>
            </div>

            {frozen.items.length > 1 && (
              <div className="mt-4 border-t border-[var(--border)] pt-3">
                <p className="text-sm font-semibold">
                  这个岗位还有其他事（共 {frozen.items.length} 件）
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {frozen.items
                    .filter((i) => i.id !== item.id)
                    .map((i) => (
                      <button
                        key={i.id}
                        type="button"
                        className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50"
                        disabled={saving}
                        onClick={() => {
                          setCurrentId(i.id);
                          setGreetingText(null);
                          setPhase("idle");
                        }}
                      >
                        <span
                          aria-hidden="true"
                          className="mr-2 inline-block h-2 w-2 rounded-full"
                          style={{ background: "#c62f24" }}
                        />
                        {i.action}
                      </button>
                    ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
function displayMaterialTitle(title: string): string {
  let t = title.replace(/（详情页原样匿名显示）/g, "");
  t = t.replace(/（CV-\d+-[^）]*）/g, "");
  if (/某/.test(t)) {
    t = t.replace(/（[^（）]*·/g, "（【猎头岗位】 ·");
  }
  return t;
}

type MaterialItem = JobMaterials["sentGreetings"][number];

export function MaterialList({
  items,
  emptyText,
  fullTextLabel,
}: {
  items: MaterialItem[];
  emptyText: string;
  fullTextLabel?: string;
}) {
  if (items.length === 0) {
    return <p className="mt-1 text-sm text-[var(--dim)]">{emptyText}</p>;
  }
  return (
    <div className="mt-2 space-y-2">
      {items.map((it) => (
        <details
          key={it.id}
          className="rounded-[var(--radius)] border border-[var(--border)] p-3"
          open={items.length === 1}
        >
          <summary className="cursor-pointer text-sm font-medium">
            {displayMaterialTitle(it.title)}
            {it.occurredAt ? (
              <span className="ml-2 text-xs font-normal text-[var(--dim)]">
                {it.occurredAt}
              </span>
            ) : null}
          </summary>
          {fullTextLabel && (
            <p className="mt-2 text-xs font-medium text-[var(--accent)]">
              {fullTextLabel}
            </p>
          )}
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">
            {it.body}
          </p>
          {it.source && (
            <p className="mt-2 text-xs text-[var(--dim)]">
              数据来源：{it.source}
            </p>
          )}
        </details>
      ))}
    </div>
  );
}
function EchoPanel({
  echo,
  onClose,
  onConfirm,
  confirming,
}: {
  echo: BatchEcho;
  onClose: () => void;
  onConfirm: (batchId: number) => void;
  confirming: boolean;
}) {
  const policy = useMuseConfiguration();
  const empty = echo.batchId == null || echo.items.length === 0;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/35 sm:items-center sm:p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !confirming) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="执行清单"
        className="max-h-[92vh] w-full max-w-[640px] overflow-y-auto rounded-t-[var(--radius)] bg-[var(--surface)] p-4 text-[var(--text)] sm:rounded-[var(--radius)]"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            {empty
              ? "执行清单"
              : `执行清单 · 第 ${echo.batchId} 批 · ${echo.items.length} 条`}
          </h3>
          <button
            type="button"
            aria-label="关闭执行清单"
            className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50"
            disabled={confirming}
            onClick={onClose}
          >
            关闭
          </button>
        </div>
        {empty ? (
          <>
            <p className="mt-2 text-sm text-[var(--dim)]">
              目前没有可执行项（需要先有「接受原稿」或「确认投递」决定，或宿主已批准待执行的岗位）。
            </p>
            {echo.excluded.length > 0 && (
              <ExcludedList excluded={echo.excluded} />
            )}
          </>
        ) : (
          <>
            <p className="mt-1 text-xs text-[var(--dim)]">
              {policy.executionSummary ??
                "确认后仅执行清单内已批准的项目；执行节奏由宿主已确认配置提供，逐条回读后更新。"}
            </p>
            <ul className="mt-2 divide-y divide-[var(--border)]">
              {echo.items.map((it) => (
                <li key={it.rank} className="py-2 text-sm">
                  <div className="flex gap-2">
                    <span className="font-mono text-[var(--dim)]">
                      #{it.rank}
                    </span>
                    <span className="font-medium">
                      {it.kind === "delivery" ? "投递" : "发送招呼"}
                    </span>
                    <span className="min-w-0 flex-1">
                      {displayCompany(it.company)} · {it.title}（{it.platform}）
                    </span>
                  </div>
                  {it.kind === "delivery" ? (
                    <p className="mt-1 pl-12 text-xs text-[var(--dim)]">
                      投递：确认后投递这个岗位。
                    </p>
                  ) : it.greetingPreview ? (
                    <p className="mt-1 whitespace-pre-wrap pl-12 text-xs leading-relaxed text-[var(--dim)]">
                      全文：{it.greetingPreview}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            {echo.excluded.length > 0 && (
              <ExcludedList excluded={echo.excluded} />
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                aria-label="确认执行这一批"
                className="flex-1 rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                disabled={confirming || echo.status === "executing"}
                onClick={() => echo.batchId != null && onConfirm(echo.batchId)}
              >
                {echo.status === "executing"
                  ? "执行中…"
                  : confirming
                    ? "启动中…"
                    : `确认执行 ${echo.items.length} 条`}
              </button>
              <button
                type="button"
                className="rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
                onClick={onClose}
              >
                先不执行
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ExcludedList({ excluded }: { excluded: BatchEcho["excluded"] }) {
  return (
    <div className="mt-2 rounded-[var(--radius)] border border-[var(--danger)] p-2">
      <p className="text-xs font-medium text-[var(--danger)]">
        以下岗位被阻塞，不在本批执行：
      </p>
      <ul className="mt-1 text-xs text-[var(--dim)]">
        {excluded.map((e) => (
          <li key={e.rank}>
            #{e.rank}：{e.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
function ExecConfirmView({
  rank,
  initialGreeting,
  onBack,
  onCloseDialog,
  onWatchBatch,
}: {
  rank: number;
  initialGreeting: string;
  onBack: () => void;
  onCloseDialog: () => void;
  onWatchBatch: (id: number) => void;
}) {
  const api = useMuseActions();
  const policy = useMuseConfiguration();
  const queryClient = useQueryClient();
  const precheck = useQuery({
    queryKey: ["exec-precheck", rank],
    queryFn: () => api.getExecPrecheck({ rank }),
  });
  const p = precheck.data;
  const isDelivery = p?.kind === "delivery";
  const [text, setText] = useState<string | null>(null);
  const textValue = text ?? initialGreeting ?? p?.greetingText ?? "";
  const [showResume, setShowResume] = useState(false);
  const resume = useQuery({
    queryKey: ["online-resume"],
    queryFn: () => api.getOnlineResume({}),
    enabled: showResume && isDelivery,
  });
  const [phase, setPhase] = useState<
    "idle" | "working" | "started" | "done" | "failed"
  >("idle");
  const [resultMsg, setResultMsg] = useState("");
  const [batchId, setBatchId] = useState<number | null>(null);

  const batchQuery = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => api.getBatch({ batchId: batchId ?? 0 }),
    enabled: batchId != null && phase === "started",
    refetchInterval: policy.refreshMs ?? false,
  });
  useEffect(() => {
    if (phase !== "started") return;
    const it = batchQuery.data?.items.find((i) => i.rank === rank);
    if (!it) return;
    if (it.status === "done") {
      setPhase("done");
      setResultMsg(
        it.detail ??
          (isDelivery ? "投递成功，已回读确认。" : "招呼已发送，已回读确认。"),
      );
      void queryClient.invalidateQueries();
    } else if (it.status === "failed") {
      setPhase("failed");
      setResultMsg(it.detail ?? "执行没有成功，没有记录到回读结果。");
      void queryClient.invalidateQueries();
    }
  }, [batchQuery.data, phase, rank]);

  async function resolveFamily() {
    setPhase("working");
    try {
      const r = await api.recordDecision({
        rank,
        kind: "resolve_block",
        note: null,
        greetingText: null,
      });
      if (!r.ok) {
        setPhase("failed");
        setResultMsg(r.message ?? "判定没有保存成功。");
        return;
      }
      void queryClient.invalidateQueries();
      setPhase("idle");
    } catch {
      setPhase("failed");
      setResultMsg("判定没有保存成功，你刚才的选择还没生效。");
    }
  }

  async function execute() {
    if (!p) return;
    setPhase("working");
    setResultMsg("");
    try {
      const textChanged =
        !isDelivery && textValue.trim() !== (p.greetingText ?? "").trim();
      if (!p.approved || textChanged) {
        const r = await api.recordDecision({
          rank,
          kind: isDelivery ? "deliver" : "accept_original",
          note: null,
          greetingText: isDelivery ? null : textValue,
        });
        if (!r.ok) {
          setPhase("failed");
          setResultMsg(r.message ?? "批准没有保存成功，还没有执行。");
          return;
        }
        const fresh = await queryClient.fetchQuery({
          queryKey: ["job", rank],
          queryFn: () => api.getJob({ rank }),
        });
        if (!fresh.decisions.some((dec) => dec.id === r.decisionId)) {
          setPhase("failed");
          setResultMsg("还不能确定批准有没有保存成功，先别重复提交。");
          return;
        }
      }
      const batch = await api.createJobExecutionBatch({ rank });
      if (batch.batchId == null) {
        setPhase("failed");
        setResultMsg(
          batch.excluded[0]?.reason ?? "这个岗位现在不能执行，还没有发送。",
        );
        void queryClient.invalidateQueries();
        return;
      }
      const conf = await api.confirmExecution({ batchId: batch.batchId });
      if (!conf.ok) {
        setPhase("failed");
        setResultMsg(conf.message ?? "执行没有启动。");
        return;
      }
      setBatchId(batch.batchId);
      onWatchBatch(batch.batchId);
      setPhase("started");
      void queryClient.invalidateQueries();
    } catch {
      setPhase("failed");
      setResultMsg("执行没有启动成功，请稍后再试。");
    }
  }

  if (precheck.isPending || !p) {
    return (
      <div className="mt-4">
        <p className="text-sm text-[var(--dim)]">
          {precheck.isPending
            ? "正在核对这个岗位能不能执行…"
            : "这个岗位不存在。"}
        </p>
        <button
          type="button"
          className="mt-3 text-sm text-[var(--accent)] underline"
          onClick={onBack}
        >
          返回岗位详情
        </button>
      </div>
    );
  }

  const confirmLabel = isDelivery ? "确认投递" : "确认发送";
  const confirmDisabled =
    p.blockReason != null ||
    phase === "working" ||
    phase === "started" ||
    phase === "done" ||
    (!isDelivery && textValue.trim().length === 0);

  return (
    <div className="mt-4">
      <div className="flex items-center gap-3">
        <h4 className="text-[15px] font-semibold">
          {isDelivery ? "确认投递" : "确认发送"}
        </h4>
        {p.approved && (
          <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
            材料已批准
          </span>
        )}
        <button
          type="button"
          className="ml-auto text-sm text-[var(--accent)] underline"
          onClick={onBack}
        >
          返回岗位详情
        </button>
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2">
        <div className="flex gap-3">
          <dt className="w-12 flex-none font-medium text-[var(--dim)]">公司</dt>
          <dd className="min-w-0">{displayCompany(p.company)}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-12 flex-none font-medium text-[var(--dim)]">渠道</dt>
          <dd className="min-w-0">{p.platform}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-12 flex-none font-medium text-[var(--dim)]">地点</dt>
          <dd className="min-w-0">{p.location || "待核实"}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-12 flex-none font-medium text-[var(--dim)]">薪资</dt>
          <dd className="min-w-0">
            {p.salary ? (
              <strong className="font-semibold">{p.salary}</strong>
            ) : (
              "待核实"
            )}
          </dd>
        </div>
      </dl>

      {isDelivery ? (
        <section
          className="mt-4 border-t border-[var(--border)] pt-3"
          aria-label="投递材料"
        >
          <h5 className="text-sm font-semibold">投递材料</h5>
          <p className="mt-1.5 text-sm leading-relaxed">
            投递的是猎聘平台上的统一在线简历，不是逐岗准备的 PDF 文件。
          </p>
          <button
            type="button"
            aria-expanded={showResume}
            className="mt-2 text-sm text-[var(--accent)] underline"
            onClick={() => setShowResume((v) => !v)}
          >
            预览在线简历
          </button>
          {showResume && (
            <div className="mt-2 rounded-[var(--radius)] border border-[var(--border)] p-3">
              {resume.isPending ? (
                <p className="text-sm text-[var(--dim)]">正在打开在线简历…</p>
              ) : resume.data ? (
                <>
                  <p className="text-xs text-[var(--dim)]">
                    内容记录于 {resume.data.recordedAt}
                    ，投递前会再回读平台上的当前版本。
                  </p>
                  <div className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed">
                    {resume.data.text}
                  </div>
                </>
              ) : (
                <p className="text-sm text-[var(--danger)]">
                  在线简历暂时打不开
                </p>
              )}
            </div>
          )}
        </section>
      ) : (
        <section
          className="mt-4 border-t border-[var(--border)] pt-3"
          aria-label="招呼语全文"
        >
          <div className="flex items-center gap-2">
            <h5 className="text-sm font-semibold">招呼语</h5>
            <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
              拟发送
            </span>
          </div>
          <textarea
            aria-label="招呼语（拟发送，可编辑）"
            className="mt-2 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-2.5 text-[15px] leading-relaxed text-[var(--text)] focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            rows={8}
            value={textValue}
            disabled={
              phase === "working" || phase === "started" || phase === "done"
            }
            onChange={(e) => setText(e.target.value)}
          />
        </section>
      )}

      <section
        className="mt-4 border-t border-[var(--border)] pt-3"
        aria-label="执行预检"
      >
        <h5 className="text-sm font-semibold">预检</h5>
        {p.blockReason ? (
          <>
            <p className="mt-1.5 text-sm font-medium text-[var(--danger)]">
              现在还不能{isDelivery ? "投递" : "发送"}：{p.blockReason}
            </p>
            {p.familyRanks.length > 0 && phase !== "done" && (
              <button
                type="button"
                aria-label="我已判定不是同一个岗位"
                disabled={phase === "working" || phase === "started"}
                className="mt-2 rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                onClick={() => void resolveFamily()}
              >
                我已判定：不是同一个岗位
              </button>
            )}
          </>
        ) : (
          <p className="mt-1.5 text-sm">
            预检通过：没有屏蔽，也没有未判定的重复岗位。
          </p>
        )}
      </section>

      {phase === "working" && (
        <p className="mt-3 text-sm text-[var(--dim)]" role="status">
          正在保存批准并启动执行…
        </p>
      )}
      {phase === "started" && (
        <p className="mt-3 text-sm text-[var(--dim)]" role="status">
          已开始执行，正在逐条回读结果。关掉弹窗也会继续，结果会写回这个岗位的记录。
        </p>
      )}
      {phase === "done" && (
        <p
          className="mt-3 text-sm font-medium text-[var(--accent)]"
          role="status"
        >
          {isDelivery ? "已投递" : "已发送"}：{resultMsg}
        </p>
      )}
      {phase === "failed" && (
        <p className="mt-3 text-sm text-[var(--danger)]" role="alert">
          没有{isDelivery ? "投递" : "发送"}成功：{resultMsg}
          这件事还保留着，处理后可以再试。
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          aria-label={confirmLabel}
          disabled={confirmDisabled}
          className="flex-1 rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          onClick={() => void execute()}
        >
          {phase === "working"
            ? "启动中…"
            : phase === "started"
              ? "执行中…"
              : phase === "done"
                ? isDelivery
                  ? "已投递"
                  : "已发送"
                : confirmLabel}
        </button>
        <button
          type="button"
          className="rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
          onClick={phase === "done" ? onCloseDialog : onBack}
        >
          {phase === "done" ? "关闭" : "先不执行"}
        </button>
      </div>
    </div>
  );
}

const EVENT_PLAIN_LABELS: Record<string, string> = {
  imported: "岗位导入",
  current_host_status_snapshot: "记录了当时的状态",
  draft_generated: "写好了招呼语",
  widget_decision: "你在卡片上做过决定",
  delivery_fact: "核对了投递结果",
  greeting_sent: "招呼语已发送",
  sent_check_proposed_not_written: "核对了已发记录",
  panel_decision: "你在面板里做过决定",
  annotation_execution_blocked: "记录了执行阻塞",
  delivery_executed: "核对了投递结果",
  execution_failed: "执行没有成功",
  feedback_hold: "反馈先搁置",
  greeting_edited: "改了一版招呼语",
  wangshen_not_submitted: "网申没有提交",
  annotation_dedup: "记录了重复岗位",
  match_computed: "评估了匹配度",
};
function JobDetailDialog({
  rank,
  initialView,
  onClose,
  onWatchBatch,
  onOpenTodo,
}: {
  rank: number;
  initialView: "detail" | "review";
  onClose: () => void;
  onWatchBatch: (id: number) => void;
  onOpenTodo: (rank: number, itemId: string) => void;
}) {
  const api = useMuseActions();
  const policy = useMuseConfiguration();
  const CV_FILES = useMuseCvFiles();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["job", rank],
    queryFn: () => api.getJob({ rank }),
  });
  const materials = useQuery({
    queryKey: ["job-materials", rank],
    queryFn: () => api.getJobMaterials({ rank }),
  });
  const todos = useQuery({
    queryKey: ["todos"],
    queryFn: () => api.getTodos({}),
  });
  const brief = useQuery({
    queryKey: ["review-brief", rank],
    queryFn: () => api.getReviewBrief({ rank }),
  });
  const channelLogin = useQuery({
    queryKey: ["channel-login"],
    queryFn: () => api.getChannelLogin({}),
  });
  const [view, setView] = useState<"detail" | "review" | "confirm">(
    initialView,
  );
  const [approvalFlow, setApprovalFlow] = useState(false);
  const [lastReviewKind, setLastReviewKind] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [greetingEdit, setGreetingEdit] = useState<string | null>(null);
  const [phase, setPhase] = useState<
    "idle" | "saving" | "saved" | "failed" | "unknown"
  >("idle");
  const [savedMsg, setSavedMsg] = useState("");
  const [draftMsg, setDraftMsg] = useState<string | null>(null);
  const [closeGuard, setCloseGuard] = useState(false);
  const [showMaterials, setShowMaterials] = useState(false);

  const d = detail.data;
  const m = materials.data;
  const job = d?.job ?? null;
  const isLiepin = job?.platform === "猎聘";
  const greetingOriginal = d?.approvedGreeting ?? d?.draftGreeting ?? "";
  const greetingValue = greetingEdit ?? greetingOriginal;
  const hasDraft = greetingOriginal.length > 0;
  const sentBodies = new Set(
    (materials.data?.sentGreetings ?? []).map((s) => s.body.trim()),
  );
  const showDraftBox = hasDraft && !sentBodies.has(greetingOriginal.trim());
  const myTodos = todos.data?.jobs.find((j) => j.rank === rank) ?? null;
  const greetingTodo =
    myTodos?.items.find((i) => i.kind === "greeting") ?? null;
  const otherTodos = (myTodos?.items ?? []).filter(
    (i) => i.kind !== "greeting",
  );
  const saving = phase === "saving";
  const dirty =
    note.trim().length > 0 ||
    (greetingEdit != null && greetingEdit !== greetingOriginal);

  const requestClose = () => {
    if (saving) return;
    if (dirty && !closeGuard) {
      setCloseGuard(true);
      return;
    }
    onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, closeGuard, saving]);

  async function decide(
    kind: DecisionKindArg,
    opts: { greetingText?: string | null; resultText: string },
  ) {
    setLastReviewKind(kind);
    setPhase("saving");
    try {
      const r = await api.recordDecision({
        rank,
        kind,
        note: note.trim() ? note.trim() : null,
        greetingText: opts.greetingText ?? null,
      });
      if (!r.ok) {
        setPhase("failed");
        return;
      }
      const fresh = await queryClient.fetchQuery({
        queryKey: ["job", rank],
        queryFn: () => api.getJob({ rank }),
      });
      if (!fresh.decisions.some((dec) => dec.id === r.decisionId)) {
        setPhase("unknown");
        void queryClient.invalidateQueries();
        return;
      }
      void queryClient.invalidateQueries();
      setSavedMsg(opts.resultText);
      setPhase("saved");
    } catch {
      setPhase("failed");
    }
  }

  async function saveDraft() {
    if (greetingEdit == null) return;
    setPhase("saving");
    try {
      const r = await api.saveGreetingDraft({ rank, text: greetingEdit });
      if (!r.ok) {
        setPhase("failed");
        return;
      }
      await queryClient.fetchQuery({
        queryKey: ["job", rank],
        queryFn: () => api.getJob({ rank }),
      });
      void queryClient.invalidateQueries();
      setGreetingEdit(null);
      setDraftMsg("修改已保存，旧版本保留在材料与历史里。");
      setPhase("idle");
    } catch {
      setPhase("failed");
    }
  }

  if (detail.isPending || !d || !job) {
    return (
      <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/35 sm:items-center sm:p-4">
        <div className="w-full max-w-[760px] rounded-t-[var(--radius)] bg-[var(--surface)] p-6 text-center text-[var(--dim)] sm:rounded-[var(--radius)]">
          {detail.isPending ? "读取这个岗位的记录中…" : "这个岗位不存在。"}
          {!detail.isPending && (
            <button
              type="button"
              className="mt-3 block w-full rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
              onClick={onClose}
            >
              关闭
            </button>
          )}
        </div>
      </div>
    );
  }

  const progressLine = d.progress
    ? d.progress + (d.progressStale ? "（可能不是最新情况）" : "")
    : d.progressError
      ? `进展没生成出来：${d.progressError}。`
      : "进展暂时没更新，稍后再看。";
  const isApprovedPending =
    job.state === "pending_greeting" || job.state === "pending_delivery";
  const showApproval =
    isApprovedPending ||
    ((job.state === "pending_review" || job.state === "revise") &&
      (isLiepin || hasDraft));
  const approvalLabel = isApprovedPending
    ? isLiepin
      ? "投递这份已批准材料"
      : "发送这份已批准材料"
    : isLiepin
      ? "审批并投递"
      : "审批并发送";
  const jobNow = job;
  const droppedChannel = droppedChannelFor(
    channelLogin.data?.channels,
    jobNow.platform,
  );

  function startApproval() {
    if (jobNow.blocked) return;
    if (!isLiepin && !isApprovedPending && greetingTodo) {
      setApprovalFlow(true);
      setView("review");
      return;
    }
    setView("confirm");
  }

  const workflowSteps: { label: string; done: boolean }[] = [
    {
      label: "评估匹配度",
      done: d.history.some((h) => h.eventKind === "match_computed"),
    },
    ...(isLiepin
      ? []
      : [
          {
            label: "写招呼语",
            done:
              hasDraft ||
              d.history.some((h) => h.eventKind === "draft_generated"),
          },
        ]),
    {
      label: isLiepin ? "批准投递" : "批准材料",
      done:
        job.state === "pending_greeting" ||
        job.state === "pending_delivery" ||
        job.state === "sent" ||
        job.state === "delivered" ||
        d.decisions.some(
          (x) => x.kind === "accept_original" || x.kind === "deliver",
        ),
    },
    {
      label: isLiepin ? "投递并核对结果" : "发送并核对结果",
      done: job.state === "sent" || job.state === "delivered",
    },
  ];
  const currentStep = workflowSteps.findIndex((s) => !s.done);

  const hasMaterials =
    (m?.sentGreetings.length ?? 0) > 0 ||
    (m?.greetingVersions.length ?? 0) > 0 ||
    (m?.cvFiles.length ?? 0) > 0 ||
    (m?.deliveries.length ?? 0) > 0 ||
    (m?.panelSync.length ?? 0) > 0 ||
    (m?.feedback.length ?? 0) > 0 ||
    d.decisions.length > 0 ||
    d.history.length > 0;

  const header = (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <h3 className="text-lg font-semibold leading-snug">
          {job.title || "岗位名称待核实"}
        </h3>
      </div>
      <button
        type="button"
        aria-label="关闭岗位详情"
        className="flex-none rounded-[var(--radius)] border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50"
        disabled={saving}
        onClick={requestClose}
      >
        关闭
      </button>
    </div>
  );
  const infoItems = (
    <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2">
      <div className="flex gap-3">
        <dt className="w-12 flex-none font-medium text-[var(--dim)]">公司</dt>
        <dd className="min-w-0">{displayCompany(job.company)}</dd>
      </div>
      <div className="flex gap-3">
        <dt className="w-12 flex-none font-medium text-[var(--dim)]">渠道</dt>
        <dd className="min-w-0">{job.platform}</dd>
      </div>
      <div className="flex gap-3">
        <dt className="w-12 flex-none font-medium text-[var(--dim)]">地点</dt>
        <dd className="min-w-0">{job.location || "待核实"}</dd>
      </div>
      <div className="flex gap-3">
        <dt className="w-12 flex-none font-medium text-[var(--dim)]">薪资</dt>
        <dd className="min-w-0">
          {job.salary ? (
            <strong className="font-semibold">{job.salary}</strong>
          ) : (
            "待核实"
          )}
        </dd>
      </div>
      <div className="flex gap-3">
        <dt className="w-12 flex-none font-medium text-[var(--dim)]">原岗位</dt>
        <dd className="min-w-0">
          {job.jobUrl ? (
            <a
              href={job.jobUrl}
              target="_blank"
              rel="noreferrer"
              className="text-[var(--accent)] underline"
            >
              打开原岗位
            </a>
          ) : (
            "暂无"
          )}
        </dd>
      </div>
    </dl>
  );

  const sectionTitle = "text-[15px] font-semibold";
  const sectionShell = "mt-5 border-t border-[var(--border)] pt-4";
  const draftBlock = showDraftBox ? (
    <div className="mt-3">
      <div className="flex items-center gap-2">
        <h4 className={sectionTitle}>招呼语</h4>
        <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-xs font-medium text-[var(--accent)]">
          拟发送
        </span>
      </div>
      <textarea
        aria-label="招呼语（拟发送，可编辑）"
        className="mt-2 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-2.5 text-[15px] leading-relaxed text-[var(--text)] focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
        rows={8}
        value={greetingValue}
        disabled={saving}
        onChange={(e) => {
          setGreetingEdit(e.target.value);
          setDraftMsg(null);
        }}
      />
      {greetingEdit != null && greetingEdit !== greetingOriginal && (
        <button
          type="button"
          aria-label="保存修改"
          className="mt-2 rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={saving}
          onClick={() => void saveDraft()}
        >
          {saving ? "正在保存……" : "保存修改"}
        </button>
      )}
      {draftMsg && (
        <p className="mt-2 text-sm text-[var(--accent)]" role="status">
          {draftMsg}
        </p>
      )}
    </div>
  ) : null;
  const sentBlocks = (m?.sentGreetings ?? []).map((sg) => (
    <div key={sg.id} className="mt-3">
      <div className="flex items-center gap-2">
        <h4 className={sectionTitle}>招呼语</h4>
        <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs font-medium text-[var(--dim)]">
          实际发送
        </span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-[15px] italic leading-relaxed text-[var(--dim)]">
        {sg.body}
      </p>
    </div>
  ));

  const feedbackLines = (
    <>
      {phase === "failed" && (
        <p className="mt-2 text-sm text-[var(--danger)]" role="alert">
          没有保存成功，你刚才的选择还没生效。
        </p>
      )}
      {phase === "unknown" && (
        <p className="mt-2 text-sm text-[var(--danger)]" role="alert">
          还不能确定有没有保存成功，先别重复提交。
        </p>
      )}
      {saving && (
        <p className="mt-2 text-sm text-[var(--dim)]" role="status">
          正在保存……
        </p>
      )}
      {closeGuard && (
        <div
          className="mt-2 rounded-[var(--radius)] border border-[var(--warn)] p-2"
          role="alert"
        >
          <p className="text-sm">你写的内容还没有保存，关闭就会丢失。</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="rounded-[var(--radius)] bg-[var(--accent)] px-3 py-1.5 text-sm text-white"
              onClick={() => setCloseGuard(false)}
            >
              继续编辑
            </button>
            <button
              type="button"
              className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-1.5 text-sm"
              onClick={onClose}
            >
              仍然关闭
            </button>
          </div>
        </div>
      )}
    </>
  );

  const workflow = (
    <ol
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"
      aria-label="工作流程"
    >
      {workflowSteps.map((s, i) => (
        <li key={s.label} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{
              background: s.done ? "var(--accent)" : "transparent",
              border:
                i === currentStep
                  ? "2px solid var(--accent)"
                  : "1.5px solid var(--border)",
            }}
          />
          <span>
            {s.label}
            {i === currentStep ? "（现在）" : ""}
          </span>
          {i < workflowSteps.length - 1 && (
            <span aria-hidden="true" className="text-[var(--dim)]">
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/35 sm:items-center sm:p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${job.title}，${displayCompany(job.company)}`}
        className="max-h-[92vh] w-full max-w-[760px] overflow-y-auto rounded-t-[var(--radius)] bg-[var(--surface)] p-4 text-[var(--text)] sm:rounded-[var(--radius)]"
      >
        {header}
        {phase !== "saved" && infoItems}
        {phase !== "saved" && droppedChannel && (
          <p className="mt-3">
            <LoginRestoreEntry channel={droppedChannel} compact />
          </p>
        )}

        {phase === "saved" ? (
          <div className="mt-4">
            <p className="text-base font-semibold">记下了。</p>
            <p className="mt-1 text-sm">{savedMsg}</p>
            {approvalFlow &&
              (lastReviewKind === "approve_text" ||
                lastReviewKind === "accept_original") && (
                <button
                  type="button"
                  aria-label={isLiepin ? "继续到确认投递" : "继续到确认发送"}
                  className="mt-3 w-full rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white"
                  onClick={() => {
                    setApprovalFlow(false);
                    setPhase("idle");
                    setView("confirm");
                  }}
                >
                  {isLiepin ? "继续到确认投递" : "继续到确认发送"}
                </button>
              )}
            <button
              type="button"
              className="mt-3 w-full rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm"
              onClick={onClose}
            >
              关闭
            </button>
          </div>
        ) : view === "confirm" ? (
          <ExecConfirmView
            key={`confirm-${rank}`}
            rank={rank}
            initialGreeting={greetingValue}
            onBack={() => setView("detail")}
            onCloseDialog={onClose}
            onWatchBatch={onWatchBatch}
          />
        ) : view === "review" ? (
          <>
            <div className="mt-4">
              <h4 className="text-sm font-semibold">JD 要点</h4>
              {brief.data?.note && (
                <p className="mt-1 text-sm text-[var(--dim)]">
                  {brief.data.note}
                </p>
              )}
              {(brief.data?.points ?? d.jdPoints).length > 0 ? (
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                  {(brief.data?.points ?? d.jdPoints).map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-sm text-[var(--dim)]">
                  还没有读到可用的职位要点。
                </p>
              )}
              {(brief.data?.keywords ?? []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(brief.data?.keywords ?? []).map((k) => (
                    <span
                      key={k}
                      className="rounded-full border border-[var(--border)] bg-[var(--bg)] px-2 py-0.5 text-xs"
                    >
                      {k}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-4">
              {draftBlock ?? (
                <p className="text-sm text-[var(--dim)]">还没有招呼语。</p>
              )}
            </div>

            {feedbackLines}

            {showDraftBox && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  aria-label="这版文案可以"
                  disabled={saving}
                  className="rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                  onClick={() =>
                    void decide("approve_text", {
                      resultText:
                        "记下了：这版文案可以。这只是文案意见，还没有批准发送。",
                    })
                  }
                >
                  这版文案可以
                </button>
                <button
                  type="button"
                  aria-label="帮我改一下"
                  disabled={saving}
                  className="rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm disabled:opacity-50"
                  onClick={() =>
                    void decide("accept_revise", {
                      resultText: "记下了：招呼语要改。改好后会再给你看。",
                    })
                  }
                >
                  帮我改一下
                </button>
                {job.state === "pending_review" || job.state === "revise" ? (
                  <button
                    type="button"
                    aria-label="批准这份材料"
                    disabled={saving}
                    className="rounded-[var(--radius)] border border-[var(--border)] px-4 py-2.5 text-sm disabled:opacity-50"
                    onClick={() =>
                      void decide("accept_original", {
                        greetingText: greetingEdit,
                        resultText:
                          "这份材料已批准。还没有发送；发送前还要在执行清单里逐条核对确认。",
                      })
                    }
                  >
                    批准这份材料
                  </button>
                ) : null}
              </div>
            )}

            {sentBlocks.length > 0 && <div className="mt-2">{sentBlocks}</div>}

            <div className="mt-4 flex flex-wrap gap-3 text-sm">
              <button
                type="button"
                className="text-[var(--accent)] underline"
                onClick={() => setView("detail")}
              >
                返回岗位详情
              </button>
              <button
                type="button"
                className="text-[var(--accent)] underline"
                onClick={() => {
                  setView("detail");
                  setShowMaterials(true);
                }}
              >
                查看材料与历史
              </button>
              {!noteOpen ? (
                <button
                  type="button"
                  className="text-[var(--accent)] underline"
                  onClick={() => setNoteOpen(true)}
                >
                  补充意见
                </button>
              ) : null}
            </div>
            {noteOpen && (
              <textarea
                aria-label="补充意见（可选）"
                className="mt-2 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-2 text-sm"
                rows={2}
                value={note}
                disabled={saving}
                onChange={(e) => setNote(e.target.value)}
                placeholder="会和你的决定一起保存"
              />
            )}
          </>
        ) : (
          <>
            <section className={sectionShell} aria-label="职位要求">
              <h4 className={sectionTitle}>职位要求</h4>
              {d.jdPoints.length > 0 ? (
                <ul className="mt-2 space-y-1.5 text-[15px] leading-relaxed">
                  {d.jdPoints.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1.5 text-sm text-[var(--dim)]">待核实</p>
              )}
              {d.completeness && d.completeness !== "完整" && (
                <p className="mt-1.5 text-xs text-[var(--dim)]">
                  职位说明不完整
                </p>
              )}
              {(brief.data?.keywords ?? []).length > 0 && (
                <div
                  className="mt-3 flex flex-wrap gap-1.5"
                  aria-label="关键词"
                >
                  {(brief.data?.keywords ?? []).map((k) => (
                    <span
                      key={k}
                      className="rounded-full border border-[var(--border)] bg-[var(--bg)] px-2 py-0.5 text-xs"
                    >
                      {k}
                    </span>
                  ))}
                </div>
              )}
              {d.jdPoints.length > 0 && (
                <details className="mt-2.5">
                  <summary className="cursor-pointer text-sm text-[var(--accent)]">
                    完整职位说明
                  </summary>
                  <p className="mt-2 text-sm leading-relaxed">
                    {d.jdPoints.join("；")}
                  </p>
                  {(d.matchStrengths.length > 0 ||
                    d.matchPartial.length > 0) && (
                    <p className="mt-2 text-sm">
                      {d.matchStrengths.length > 0 &&
                        `比较接近的部分：${d.matchStrengths.join("；")}。`}
                      {d.matchPartial.length > 0 &&
                        ` 部分接近：${d.matchPartial.join("；")}。`}
                    </p>
                  )}
                  {(() => {
                    const verify = [
                      ...new Set([
                        ...(d.gaps ?? []),
                        ...(d.matchUncertainties ?? []),
                        ...(d.matchHardGaps ?? []),
                        ...(d.hardFilterReasons ?? []),
                      ]),
                    ].filter(
                      (p) =>
                        !/evidence_items|admissible|DB\b|SQL|字段名|队列路径/.test(
                          p,
                        ),
                    );
                    return verify.length > 0 ? (
                      <>
                        <p className="mt-2 text-sm font-medium">还需要核实</p>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                          {verify.slice(0, 3).map((p, i) => (
                            <li key={i}>{p}</li>
                          ))}
                        </ul>
                        {verify.length > 3 && (
                          <p className="mt-1 text-xs text-[var(--dim)]">
                            其余 {verify.length - 3} 项由宿主继续核对。
                          </p>
                        )}
                      </>
                    ) : null;
                  })()}
                </details>
              )}
            </section>

            <section className={sectionShell} aria-label="进展">
              <h4 className={sectionTitle}>进展</h4>
              <p className="mt-1.5 text-[15px] leading-relaxed">
                {progressLine}
              </p>
            </section>

            {job.blocked && (
              <div className="mt-3 rounded-[var(--radius)] border border-[var(--danger)] p-3">
                <p className="text-sm font-medium text-[var(--danger)]">
                  {job.blockedKind === "shield"
                    ? "这个岗位被屏蔽挡住了"
                    : "这个岗位与另一个岗位重复"}
                </p>
                <p className="mt-1 text-sm">{job.blockedNote}</p>
                <button
                  type="button"
                  aria-label="我已判定，解除阻塞"
                  disabled={saving}
                  className="mt-2 rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  onClick={() =>
                    void decide("resolve_block", {
                      resultText:
                        "阻塞已按你的判定解除。这个岗位接下来是否推进，按它的其他事项继续处理。",
                    })
                  }
                >
                  我已判定，解除阻塞
                </button>
              </div>
            )}

            {(greetingTodo ||
              otherTodos.length > 0 ||
              job.state === "pending_greeting" ||
              job.state === "pending_delivery") && (
              <section className={sectionShell} aria-label="待你处理">
                <h4 className={sectionTitle}>待你处理</h4>
                <div className="mt-2 space-y-2">
                  {greetingTodo && !isLiepin && hasDraft && (
                    <button
                      type="button"
                      aria-label="看看招呼语"
                      className="flex w-full items-center gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-left text-sm"
                      onClick={() => setView("review")}
                    >
                      <span
                        aria-hidden="true"
                        className="h-2.5 w-2.5 flex-none rounded-full"
                        style={{ background: "#c62f24" }}
                      />
                      看看招呼语
                    </button>
                  )}
                  {otherTodos.map((i) => (
                    <button
                      key={i.id}
                      type="button"
                      aria-label={i.action}
                      className="flex w-full items-center gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-left text-sm"
                      onClick={() => onOpenTodo(rank, i.id)}
                    >
                      <span
                        aria-hidden="true"
                        className="h-2.5 w-2.5 flex-none rounded-full"
                        style={{ background: "#c62f24" }}
                      />
                      {i.action}
                      <span className="text-[var(--dim)]">{i.question}</span>
                    </button>
                  ))}
                  {(job.state === "pending_greeting" ||
                    job.state === "pending_delivery") && (
                    <button
                      type="button"
                      aria-label={
                        isLiepin ? "投递这份已批准材料" : "发送这份已批准材料"
                      }
                      className="w-full rounded-[var(--radius)] bg-[var(--accent)] px-3 py-2.5 text-left text-sm font-medium text-white"
                      onClick={startApproval}
                    >
                      {isLiepin ? "投递这份已批准材料" : "发送这份已批准材料"}
                    </button>
                  )}
                </div>
              </section>
            )}

            {!isLiepin && (
              <section className={sectionShell} aria-label="招呼语">
                {draftBlock}
                {sentBlocks}
                {!hasDraft && sentBlocks.length === 0 && (
                  <div className="flex items-center gap-2">
                    <h4 className={sectionTitle}>招呼语</h4>
                    <span className="text-sm text-[var(--dim)]">还没有</span>
                  </div>
                )}
              </section>
            )}

            {feedbackLines}

            {((m?.cvFiles ?? []).length > 0 ||
              (m?.deliveries ?? []).length > 0) && (
              <section className={sectionShell} aria-label="简历">
                <h4 className={sectionTitle}>简历</h4>
                {(m?.cvFiles ?? []).length > 0 && (
                  <ul className="mt-2 space-y-2.5">
                    {(m?.cvFiles ?? []).map((f) => {
                      const cv = CV_FILES[rank];
                      const url = f.title.includes("v2") ? cv?.v2 : cv?.v1;
                      return (
                        <li key={f.id} className="text-sm">
                          <p className="font-medium">
                            {displayMaterialTitle(f.title)}
                          </p>
                          {f.body && (
                            <p className="mt-0.5 text-[var(--dim)]">{f.body}</p>
                          )}
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-1.5 inline-block rounded-[var(--radius)] bg-[var(--accent)] px-3 py-1.5 text-sm text-white"
                              aria-label={`打开预览 ${f.title}`}
                            >
                              打开预览（PDF）
                            </a>
                          ) : (
                            <p className="mt-1.5 text-sm text-[var(--danger)]">
                              简历暂时打不开
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                {isLiepin &&
                  (m?.cvFiles ?? []).length === 0 &&
                  (m?.deliveries ?? []).length > 0 && (
                    <p className="mt-1.5 text-sm text-[var(--dim)]">
                      统一在线简历
                    </p>
                  )}
                {(m?.deliveries ?? []).length > 0 && (
                  <MaterialList items={m?.deliveries ?? []} emptyText="" />
                )}
              </section>
            )}

            <div className="mt-4 flex flex-wrap gap-3 text-sm">
              <button
                type="button"
                aria-expanded={showMaterials}
                className="text-[var(--accent)] underline"
                onClick={() => setShowMaterials((v) => !v)}
              >
                查看材料与历史
              </button>
              {!noteOpen && (
                <button
                  type="button"
                  className="text-[var(--accent)] underline"
                  onClick={() => setNoteOpen(true)}
                >
                  补充意见
                </button>
              )}
            </div>

            {showMaterials && (
              <div className="mt-3 rounded-[var(--radius)] border border-[var(--border)] p-3">
                {materials.isPending ? (
                  <p className="text-sm text-[var(--dim)]">
                    读取这个岗位保存的材料中…
                  </p>
                ) : !hasMaterials ? (
                  <p className="text-sm text-[var(--dim)]">
                    暂时没有找到其他历史材料。
                  </p>
                ) : (
                  <>
                    {(m?.greetingVersions ?? []).length > 0 && (
                      <>
                        <p className="text-sm font-semibold">以前的招呼语</p>
                        <MaterialList
                          items={m?.greetingVersions ?? []}
                          emptyText=""
                        />
                      </>
                    )}
                    {(m?.panelSync ?? []).length > 0 && (
                      <>
                        <p className="mt-3 text-sm font-semibold">投递安排</p>
                        <MaterialList items={m?.panelSync ?? []} emptyText="" />
                      </>
                    )}
                    <p className="mt-3 text-sm">沟通记录：还没有</p>
                    {d.decisions.length > 0 && (
                      <>
                        <p className="mt-3 text-sm font-semibold">我的决定</p>
                        <ul className="mt-2 space-y-1 text-sm">
                          {d.decisions.map((dec) => (
                            <li key={dec.id} className="flex flex-wrap gap-x-2">
                              <span className="text-[var(--dim)]">
                                {new Date(dec.createdAt).toLocaleString(
                                  "zh-CN",
                                  { timeZone: "Asia/Shanghai" },
                                )}
                              </span>
                              <span>
                                {DECISION_KIND_LABELS[dec.kind] ?? dec.kind}
                              </span>
                              {dec.note && <span>备注：{dec.note}</span>}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                    {(m?.feedback ?? []).length > 0 && (
                      <MaterialList items={m?.feedback ?? []} emptyText="" />
                    )}
                    {d.history.length > 0 && (
                      <>
                        <p className="mt-3 text-sm font-semibold">做过的事</p>
                        <ul className="mt-2 space-y-1.5 text-sm">
                          {d.history.map((h) => (
                            <li key={h.id}>
                              <span className="font-medium">
                                {EVENT_PLAIN_LABELS[h.eventKind] ??
                                  "做过一项工作"}
                              </span>
                              <span className="ml-2 text-xs text-[var(--dim)]">
                                {h.occurredAt ?? "时间未保存"}
                              </span>
                              <span className="block text-[var(--dim)]">
                                {plainText(h.detail)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </>
                )}
              </div>
            )}

            {noteOpen && (
              <textarea
                aria-label="补充意见（可选）"
                className="mt-3 w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-2 text-sm"
                rows={2}
                value={note}
                disabled={saving}
                onChange={(e) => setNote(e.target.value)}
                placeholder="会和你的决定一起保存"
              />
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              {showApproval && (
                <button
                  type="button"
                  aria-label={approvalLabel}
                  disabled={saving || job.blocked}
                  className="rounded-[var(--radius)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  onClick={startApproval}
                >
                  {approvalLabel}
                </button>
              )}
              {job.state !== "declined" && job.state !== "closed" ? (
                <button
                  type="button"
                  aria-label="放弃这个岗位"
                  disabled={saving}
                  className="rounded-[var(--radius)] bg-[var(--danger)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  onClick={() =>
                    void decide("decline", {
                      resultText: "这个岗位已放弃，不再推进。",
                    })
                  }
                >
                  放弃这个岗位
                </button>
              ) : (
                <button
                  type="button"
                  aria-label="继续了解这个岗位"
                  disabled={saving}
                  className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                  onClick={() =>
                    void decide("reopen", {
                      resultText: "这个岗位重新打开了。",
                    })
                  }
                >
                  继续了解这个岗位
                </button>
              )}
            </div>

            {showApproval && job.blocked && job.blockedNote && (
              <p className="mt-2 text-sm text-[var(--danger)]">
                现在还不能{isLiepin ? "投递" : "发送"}：{job.blockedNote}
              </p>
            )}

            <div className="mt-4 border-t border-[var(--border)] pt-3">
              {workflow}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
