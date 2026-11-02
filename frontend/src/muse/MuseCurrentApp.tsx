import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  MuseGetTableDataResponseRowsItem as Row,
  MuseGetTodosResponseJobsItem as TodoJob,
  MuseGetJobResponse as JobDetail,
  MuseCreateExecutionBatchResponse as Batch,
  MuseRecordDecisionRequest as Decision,
} from "./contracts";
import {
  useMuseActions,
  useMuseConfiguration,
  useMuseCvFiles,
} from "./context";
import {
  sortRows,
  rowMatchesFilter,
  loadSortMode,
  saveSortMode,
  plainText,
  fmtRunTime,
  MaterialList,
} from "./MuseApp";
import { saveMuseDecision } from "./decisions";
import "./current.css";
import { ChannelTag } from "./ChannelTag";
import {
  SelectionQueueBar,
  SelectionCheckbox,
  RegenerateGreetingControl,
  GreetingSignals,
  ExecutionWorkflow,
  ExecutionProgress,
} from "./SyncControls";

type Tab = "progress" | "runs" | "comms" | "about";
type Filter = "all" | "active" | "todo" | "waiting" | "ended";
const txt = (v: unknown) => (typeof v === "string" ? v : "");
const terminal = (r: Row) => r.state === "declined" || r.state === "closed";
const safeUrl = (url: string | null | undefined) =>
  url && /^(https?:\/\/|\/[^/])/.test(url) ? url : null;

function Modal({
  title,
  wide = false,
  children,
  onClose,
  busy = false,
}: {
  title: string;
  wide?: boolean;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    box.current?.focus();
    return () => {
      document.body.style.overflow = old;
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="scrim open"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) close.current();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) {
          e.stopPropagation();
          close.current();
        }
        if (e.key === "Tab") {
          const nodes = Array.from(
            box.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled),a[href],textarea:not(:disabled),summary,[tabindex="0"]',
            ) ?? [],
          );
          const first = nodes[0],
            last = nodes.at(-1);
          if (
            e.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === box.current)
          ) {
            e.preventDefault();
            last?.focus();
          } else if (
            !e.shiftKey &&
            (document.activeElement === last ||
              document.activeElement === box.current)
          ) {
            e.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <div
        ref={box}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal${wide ? " wide" : ""}`}
      >
        <button
          className="x"
          aria-label="关闭"
          disabled={busy}
          onClick={onClose}
        >
          ×
        </button>
        {children}
      </div>
    </div>
  );
}
function Meta({ job, row }: { job: NonNullable<JobDetail["job"]>; row?: Row }) {
  return (
    <div className="meta">
      {job.company ? `${job.company} · ` : ""}
      <ChannelTag channel={job.platform} /> · {job.location ?? "地点待核实"} ·{" "}
      <span className="salary">{job.salary ?? "薪资待核实"}</span> · 入库{" "}
      {row?.intakeAt ? row.intakeAt.slice(0, 10) : "时间未记录"}
    </div>
  );
}
function Points({ values }: { values: string[] }) {
  return (
    <ul className="pts">
      {values.map((v, i) => (
        <li key={i}>{plainText(v)}</li>
      ))}
    </ul>
  );
}

export function MuseCurrentApp() {
  const api = useMuseActions(),
    policy = useMuseConfiguration(),
    client = useQueryClient();
  const [tab, setTab] = useState<Tab>("progress"),
    [filter, setFilter] = useState<Filter>("todo"),
    [sort, setSort] = useState(loadSortMode);
  const [selection, setSelection] = useState<{
    rank: number;
    todo?: TodoJob["items"][number];
  } | null>(null);
  const [watchBatch, setWatchBatch] = useState<number | null>(null);
  const [excludedCount, setExcludedCount] = useState(0);
  const watch = (id: number, excluded = 0) => {
    setWatchBatch(id);
    setExcludedCount(excluded);
  };
  const [batch, setBatch] = useState<Batch | null>(null),
    [notice, setNotice] = useState("");
  const snapshot = useQuery({
    queryKey: ["console-snapshot"],
    queryFn: () => api.getConsoleSnapshot({}),
    refetchInterval: policy.refreshMs ?? false,
  });
  const enabled = !!snapshot.data?.seeded;
  const table = useQuery({
    queryKey: ["table-data"],
    queryFn: () => api.getTableData({}),
    enabled,
    refetchInterval: policy.refreshMs ?? false,
  });
  const todos = useQuery({
    queryKey: ["todos"],
    queryFn: () => api.getTodos({}),
    enabled,
    refetchInterval: policy.refreshMs ?? false,
  });
  const channels = useQuery({
    queryKey: ["channel-login"],
    queryFn: () => api.getChannelLogin({}),
    enabled,
    refetchInterval: policy.refreshMs ?? false,
  });
  const echo = useMutation({
    mutationFn: () => api.createExecutionBatch({}),
    onSuccess: (r) => setBatch(r),
    onError: () => setNotice("执行清单读取未完成，请先核验。"),
  });
  const sync = useMutation({
    mutationFn: () => api.syncFromHost({}),
    onSuccess: (r) => {
      setNotice(r.message);
      void client.invalidateQueries();
    },
    onError: () => setNotice("刷新未完成，当前保留已有记录。"),
  });
  const rows = table.data?.rows ?? [],
    todoRanks = new Set(todos.data?.jobs.map((j) => j.rank) ?? []);
  const filters: [Filter, string][] = [
    ["all", "全部"],
    ["active", "正在推进"],
    ["todo", "等你处理"],
    ["waiting", "等待对方"],
    ["ended", "已结束"],
  ];
  const visible = sortRows(rows, sort).filter((r) =>
    rowMatchesFilter(r, filter, todoRanks),
  );
  const source = snapshot.data?.snapshot;
  return (
    <div className="muse-current">
      <div className="topbar">
        <div className="topbar-in" role="tablist" aria-label="看板页面">
          {(
            [
              ["progress", "任务进度"],
              ["runs", "运行记录"],
              ["comms", "沟通进展"],
              ["about", "数据说明"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              className="navtab"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="wrap">
        {snapshot.isError ? (
          <p role="alert">来源尚未接通，未切换为演示；请核对宿主连接。</p>
        ) : snapshot.isPending ? (
          <p role="status" className="empty">
            读取队列中…
          </p>
        ) : !enabled ? (
          <p role="alert">宿主队列尚未接入，请先由宿主加载已有记录。</p>
        ) : (
          <>
            {tab === "progress" && (
              <section aria-label="岗位进展">
                <div className="head-row">
                  <h1>岗位进展</h1>
                  <div className="head-ctl">
                    <div
                      role="group"
                      aria-label="排序方式"
                      style={{ display: "flex", gap: 8 }}
                    >
                      {(
                        [
                          ["match", "按匹配度"],
                          ["intake", "按入库时间"],
                        ] as const
                      ).map(([key, label]) => (
                        <button
                          key={key}
                          className={`ctl${sort === key ? " on" : ""}`}
                          aria-pressed={sort === key}
                          onClick={() => {
                            setSort(key);
                            saveSortMode(key);
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <button
                      className="ctl"
                      disabled={sync.isPending}
                      onClick={() => sync.mutate()}
                    >
                      {sync.isPending ? "刷新中…" : "刷新"}
                    </button>
                    <button
                      className="ctl primary"
                      disabled={
                        echo.isPending ||
                        table.isError ||
                        todos.isError ||
                        !!policy.readonlyReason
                      }
                      onClick={() => echo.mutate()}
                    >
                      执行清单
                    </button>
                  </div>
                </div>
                <div className="filters" role="tablist" aria-label="岗位筛选">
                  {filters.map(([key, label]) => (
                    <button
                      key={key}
                      className="ftab"
                      role="tab"
                      aria-selected={filter === key}
                      onClick={() => setFilter(key)}
                    >
                      {label}
                      {key === "todo" && !!todoRanks.size && (
                        <span className="rdot" />
                      )}
                      <span
                        className={`cnt num${key === "todo" ? " red" : ""}`}
                      >
                        {(key === "todo" && !todos.data) || !table.data
                          ? "?"
                          : rows.filter((r) =>
                              rowMatchesFilter(r, key, todoRanks),
                            ).length}
                      </span>
                    </button>
                  ))}
                </div>
                {(table.isError || todos.isError) && (
                  <p role="alert">
                    {table.isError
                      ? "岗位列表读取未完成。"
                      : "待办来源读取未完成，数量尚不确定。"}
                  </p>
                )}
                <SelectionQueueBar
                  visibleRanks={visible.map((r) => r.rank)}
                  onWatch={watch}
                />
                {watchBatch != null && (
                  <ExecutionProgress
                    batchId={watchBatch}
                    excludedCount={excludedCount}
                    onClose={() => setWatchBatch(null)}
                  />
                )}
                <div className="card">
                  <div className="trow head">
                    <span>选</span>
                    {["岗位", "渠道", "匹配情况", "进展", "待你处理"].map(
                      (h) => (
                        <span key={h}>
                          {h}
                          {h === "进展" && (
                            <small
                              style={{
                                display: "block",
                                fontSize: 11,
                                fontWeight: 400,
                              }}
                              title="由宿主 AI 根据已保存、已核实的记录填写，只简述当前结果、等待或阻碍。"
                            >
                              AI 填写 · 约20～50字
                            </small>
                          )}
                        </span>
                      ),
                    )}
                  </div>
                  <div>
                    {table.isPending ? (
                      <div className="empty">读取岗位中…</div>
                    ) : !visible.length && !table.isError ? (
                      <div className="empty">
                        {filter === "todo" && !todos.data
                          ? "待办来源尚未接入，无法确定这一类岗位。"
                          : "这一类现在是空的。"}
                      </div>
                    ) : (
                      visible.map((row) => {
                        const todo = todos.data?.jobs.find(
                          (t) => t.rank === row.rank,
                        )?.items[0];
                        return (
                          <div
                            key={row.rank}
                            className="trow"
                            data-open={row.rank}
                            tabIndex={0}
                            role="button"
                            aria-label={`查看详情：${row.title}`}
                            onClick={() => setSelection({ rank: row.rank })}
                            onKeyDown={(e) => {
                              if (
                                e.target === e.currentTarget &&
                                (e.key === "Enter" || e.key === " ")
                              ) {
                                e.preventDefault();
                                setSelection({ rank: row.rank });
                              }
                            }}
                          >
                            <SelectionCheckbox
                              rank={row.rank}
                              title={row.title}
                            />
                            <div className="cell" data-label="岗位">
                              <div className="job-t">{row.title}</div>
                              <div className="job-c">{row.company}</div>
                            </div>
                            <div className="cell" data-label="渠道">
                              <ChannelTag channel={row.channel} />
                            </div>
                            <div className="cell" data-label="匹配情况">
                              <ul className="match">
                                {row.matchBullets.map((b, i) => (
                                  <li key={i}>{plainText(b)}</li>
                                ))}
                              </ul>
                            </div>
                            <div className="cell prog" data-label="进展">
                              {row.progress
                                ? plainText(row.progress)
                                : row.progressError
                                  ? `进展未更新：${row.progressError}`
                                  : "进展尚未接入，当前情况待核实。"}
                            </div>
                            <div className="cell" data-label="待你处理">
                              {todo && (
                                <button
                                  className="todo-btn"
                                  aria-label={`${row.title}：${todo.action}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSelection({ rank: row.rank, todo });
                                  }}
                                >
                                  <span className="dot" />
                                  {todo.action}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </section>
            )}
            {tab === "runs" && (
              <section>
                <div className="head-row">
                  <h1>运行记录</h1>
                </div>
                <div className="card" style={{ marginTop: 14 }}>
                  <div className="srow head cols-run">
                    <span>时间</span>
                    <span>已完成的工作</span>
                    <span>登录状态</span>
                  </div>
                  {source?.runs.length ? (
                    source.runs.map((r, i) => (
                      <div key={i} className="srow cols-run">
                        <span className="num">
                          {fmtRunTime(r.run.created_at) || "时间未记录"}
                        </span>
                        <span>
                          <b>{txt(r.run.executor) || "执行者未记录"}</b> ·{" "}
                          {r.activities
                            .map((a) =>
                              plainText(txt(a.message) || "工作详情尚未接入"),
                            )
                            .join("；") || "运行详情尚未接入"}
                          {r.run.status !== "completed" && "（完成状态待核对）"}
                        </span>
                        <span>
                          {channels.data?.channels.length
                            ? channels.data.channels.map((c, index) => (
                                <span key={c.channel}>
                                  {index > 0 ? " · " : ""}
                                  <ChannelTag channel={c.channel} />{" "}
                                  {c.status === "ok"
                                    ? "已登录"
                                    : c.status === "dropped"
                                      ? "登录失效"
                                      : "状态待核对"}
                                </span>
                              ))
                            : "登录状态尚未接入"}
                        </span>
                      </div>
                    ))
                  ) : (
                    <div className="empty">运行记录尚未接入或尚未保存。</div>
                  )}
                </div>
              </section>
            )}
            {tab === "comms" && (
              <section>
                <div className="head-row">
                  <h1>沟通进展</h1>
                </div>
                <div className="card" style={{ marginTop: 14 }}>
                  <div className="srow head cols-comm">
                    <span>岗位</span>
                    <span>渠道</span>
                    <span>最新沟通</span>
                    <span>状态</span>
                  </div>
                  {rows.filter((r) => r.contacted).length ? (
                    rows
                      .filter((r) => r.contacted)
                      .map((r) => (
                        <div key={r.rank} className="srow cols-comm">
                          <button
                            onClick={() => setSelection({ rank: r.rank })}
                          >
                            <b>{r.title}</b>
                          </button>
                          <span>
                            <ChannelTag channel={r.channel} />
                          </span>
                          <span>
                            {r.progress ||
                              "已有联系记录；对方是否回复尚未核实。"}
                          </span>
                          <span>{terminal(r) ? "已结束" : "等待对方"}</span>
                        </div>
                      ))
                  ) : (
                    <div className="empty">
                      当前没有接入已核验的沟通记录，对方回复情况尚不确定。
                    </div>
                  )}
                </div>
              </section>
            )}
            {tab === "about" && (
              <section>
                <div className="head-row">
                  <h1>数据说明</h1>
                </div>
                <div className="card doc" style={{ marginTop: 14 }}>
                  <h2>计数口径</h2>
                  <ul>
                    <li>
                      <b>全部</b>：队列里的全部岗位。
                    </li>
                    <li>
                      <b>正在推进</b>
                      ：还没有结束的岗位，包含等你处理和等待对方的。
                    </li>
                    <li>
                      <b>等你处理</b>
                      ：带未处理个人待办的岗位数，一个岗位有多个待办也只算一次；红点只表示这一件待办还没处理。
                    </li>
                    <li>
                      <b>等待对方</b>
                      ：已经发送或投递、在等对方回复或查看的岗位。
                    </li>
                    <li>
                      <b>已结束</b>
                      ：已拒绝、已放弃或已过观察期的岗位，排在列表最后。
                    </li>
                  </ul>
                  <h3>列表怎么读</h3>
                  <ul>
                    <li>
                      「匹配情况」写两点：基本要求核对的结果，和对得上的经历，不用分数当结论。
                    </li>
                    <li>
                      「进展」由宿主 AI
                      根据本岗位已保存、已核实的记录填写，约20～50字，只说明当前结果、等待或阻碍。
                      例如：“BOSS
                      执行失败，发送结果尚未确认，请检查登录状况后核验。”或“招呼语已发送成功并回读确认，目前等待
                      HR 回复。”
                      例句只说明语气，不是固定模板；缺少记录时说明未知，不推断失败原因或对方是否回复。薪资在详情里加粗显示。
                    </li>
                    <li>
                      「待你处理」只在有待办时出现按钮，写清要你做的那一件具体事；点按钮打开待办弹窗，点行打开详情弹窗。
                    </li>
                  </ul>
                  <h3>决定和执行是两步</h3>
                  <p>
                    在弹窗里点接受、批准，只记录决定，不会直接发送或投递；到执行清单里核对完点「确认执行」，才逐条发送或投递，并逐条回读结果。右上角关闭只结束查看，不改状态、不清待办。
                  </p>
                </div>
              </section>
            )}
          </>
        )}
      </div>
      {selection && (
        <CurrentJobDialog
          key={`${selection.rank}:${selection.todo?.id ?? "detail"}`}
          rank={selection.rank}
          todo={selection.todo}
          row={rows.find((r) => r.rank === selection.rank)}
          onClose={() => setSelection(null)}
          onNotice={setNotice}
          onWatch={watch}
        />
      )}
      {batch && (
        <CurrentExecution
          echo={batch}
          onClose={() => setBatch(null)}
          onNotice={setNotice}
          onWatch={watch}
        />
      )}
      {notice && (
        <div className="toast show" role="status">
          {notice}
        </div>
      )}
    </div>
  );
}

function CurrentJobDialog({
  rank,
  row,
  todo,
  onClose,
  onNotice,
  onWatch,
}: {
  rank: number;
  row?: Row;
  todo?: TodoJob["items"][number];
  onClose: () => void;
  onNotice: (s: string) => void;
  onWatch: (id: number) => void;
}) {
  const api = useMuseActions(),
    client = useQueryClient(),
    files = useMuseCvFiles(),
    policy = useMuseConfiguration();
  const detail = useQuery({
    queryKey: ["job", rank],
    queryFn: () => api.getJob({ rank }),
  });
  const materials = useQuery({
    queryKey: ["job-materials", rank],
    queryFn: () => api.getJobMaterials({ rank }),
  });
  const [edit, setEdit] = useState<string | null>(null),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false),
    [locked, setLocked] = useState(false),
    [error, setError] = useState("");
  const [guard, setGuard] = useState(false),
    [showNote, setShowNote] = useState(false);
  const d = detail.data,
    j = d?.job,
    text = edit ?? d?.draftGreeting ?? "",
    sent = materials.data?.sentGreetings ?? [];
  const liepin = j?.platform.includes("猎聘"),
    ended = j?.group === "closed",
    hasDraft =
      !!text && (!sent.some((s) => s.body === text) || !row?.contacted);
  const close = () => {
    if (busy) return;
    if (((edit !== null && edit !== d?.draftGreeting) || note) && !guard) {
      setGuard(true);
      return;
    }
    onClose();
  };
  async function decide(kind: Decision["kind"]) {
    if (busy || locked) return;
    setBusy(true);
    setError("");
    try {
      if (
        !liepin &&
        text !== (d?.draftGreeting ?? "") &&
        ["accept_original", "deliver"].includes(kind)
      ) {
        const saved = await api.saveGreetingDraft({ rank, text });
        if (!saved.ok) {
          setError(saved.message ?? "修改未保存，请先核验。");
          if (saved.error === "outcome_unknown") setLocked(true);
          return;
        }
        const fresh = await api.getJob({ rank });
        if (fresh.draftGreeting !== text) {
          setLocked(true);
          setError("修改回读不一致，请先核验，不重复提交。");
          return;
        }
      }
      const result = await saveMuseDecision(api, client, {
        rank,
        kind,
        note: note || null,
        greetingText:
          !liepin && ["accept_original", "approve_text"].includes(kind)
            ? text
            : null,
      });
      if (result.status !== "saved") {
        setError(result.message);
        setLocked(result.status === "unknown");
        return;
      }
      onNotice(
        kind === "resolve_block" || kind === "skip"
          ? "已记录判定，发送与投递仍需单独确认。"
          : kind === "decline"
            ? "已记录：岗位不合适，记录保留可查。"
            : kind === "accept_revise"
              ? "已记录反馈，等新版材料再单独决定；这次不发送。"
              : "已记录：进入执行安排；在执行清单确认后才会发送或投递。",
      );
      onClose();
    } catch {
      setLocked(true);
      setError("保存结果未知，请先核验，不要重复提交。");
    } finally {
      setBusy(false);
    }
  }
  const approval = () => void decide(liepin ? "deliver" : "accept_original");
  const blocked = busy || locked || !!policy.readonlyReason;
  return (
    <Modal
      title={todo ? todo.question : (j?.title ?? "岗位详情")}
      onClose={close}
      busy={busy}
    >
      {!d || !j ? (
        <p role={detail.isError ? "alert" : "status"}>
          {detail.isError
            ? "岗位来源读取未完成，详情尚不确定。"
            : "读取这个岗位的记录中…"}
        </p>
      ) : (
        <>
          {todo ? (
            <p className="q-lead">{todo.question}</p>
          ) : (
            <h2>{j.title}</h2>
          )}
          <Meta job={j} row={row} />
          {todo ? (
            <>
              <h3>依据</h3>
              <Points
                values={[
                  ...todo.reasons,
                  ...d.jdPoints.slice(0, 2).map((p) => `岗位要求：${p}`),
                  ...(row?.progress ? [`进展：${row.progress}`] : []),
                  "取舍：确认类选择只进入执行安排，真正发送 / 投递在执行清单里二次确认后才发生。",
                ]}
              />
            </>
          ) : (
            <>
              <h3>匹配情况</h3>
              <ul className="match">
                {(
                  row?.matchBullets ?? [
                    ...d.matchStrengths,
                    ...d.matchPartial,
                    ...d.matchUncertainties,
                  ]
                ).map((v, i) => (
                  <li key={i}>{plainText(v)}</li>
                ))}
              </ul>
              <h3>进展</h3>
              <div className="progbox">
                {d.progress ||
                  row?.progress ||
                  "进展尚未接入，当前情况待核实。"}
              </div>
              <h3>岗位要点</h3>
              {d.jdPoints.length ? (
                <Points values={d.jdPoints} />
              ) : (
                <p className="fact">岗位原文尚未接入。</p>
              )}
              {!![...d.gaps, ...d.matchUncertainties, ...d.matchHardGaps]
                .length && (
                <>
                  <h3>待核实</h3>
                  <Points
                    values={[
                      ...new Set([
                        ...d.gaps,
                        ...d.matchUncertainties,
                        ...d.matchHardGaps,
                      ]),
                    ]}
                  />
                </>
              )}
            </>
          )}
          {!liepin && hasDraft && todo?.kind !== "failure" ? (
            <>
              <h3>招呼稿（可编辑）</h3>
              <textarea
                className="greet"
                aria-label="招呼稿（可编辑）"
                value={text}
                disabled={blocked}
                onChange={(e) => setEdit(e.target.value)}
              />
              <RegenerateGreetingControl
                rank={rank}
                text={text}
                previousText={d.draftGreeting ?? ""}
                disabled={blocked || !!ended}
                onSaved={() => setEdit(null)}
                onBusy={setBusy}
                onUnknown={() => setLocked(true)}
              />
              {!todo && (
                <>
                  <div className="btnrow">
                    <button
                      className="btn"
                      disabled={blocked || ended}
                      onClick={approval}
                    >
                      接受原文
                    </button>
                    <button
                      className="btn"
                      disabled={blocked || ended}
                      onClick={() => setShowNote(true)}
                    >
                      岗位行，稿要改
                    </button>
                    <button
                      className="btn"
                      disabled={blocked || ended}
                      onClick={() => void decide("decline")}
                    >
                      岗位不合适
                    </button>
                  </div>
                  <p className="fact" style={{ marginTop: 8 }}>
                    接受原文 =
                    岗位合适、这份稿也行，批准当前全文；稿要改只记录反馈，等新稿再单独定；以上都只记录决定，不会直接发送。
                  </p>
                </>
              )}
            </>
          ) : (
            liepin && (
              <>
                <h3>投递材料</h3>
                <div className="progbox">
                  {materials.isError
                    ? "材料来源读取未完成。"
                    : materials.data?.cvFiles.length
                      ? "已保存的材料如下，投递前仍需你确认。"
                      : "实际简历来源尚未接入，请先由宿主提供成品。"}
                </div>
              </>
            )
          )}
          {!!sent.length && (
            <>
              <h3>实际已发送</h3>
              {sent.map((s) => (
                <p className="fact preserve-lines" key={s.id}>
                  {s.body}
                </p>
              ))}
            </>
          )}
          {(materials.data?.cvFiles ?? []).map((f) => {
            const url =
              safeUrl(f.source) ||
              safeUrl(
                f.title.includes("v2") ? files[rank]?.v2 : files[rank]?.v1,
              );
            return (
              <div key={f.id}>
                <p>{f.title}</p>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer">
                    打开预览（PDF）
                  </a>
                ) : (
                  <p className="fact">简历预览尚未接入</p>
                )}
              </div>
            );
          })}
          {todo ? (
            <div>
              {todo.kind === "failure" && (
                <ExecutionWorkflow detail={d} onWatch={onWatch} />
              )}
              {(todo.kind === "failure"
                ? []
                : todo.kind === "block"
                  ? [
                      [
                        "解除屏蔽后投递",
                        "解除屏蔽，进入投递安排，执行后回读确认。",
                        "resolve_block",
                      ],
                      [
                        "先跳过这个岗位",
                        "这次不投这个岗位，保留在正在推进里。",
                        "skip",
                      ],
                      ["岗位不合适", "整岗结束，不再处理。", "decline"],
                    ]
                  : liepin
                    ? [
                        [
                          "确认投递安排",
                          "按现在的材料投递，执行后逐条回读确认。",
                          "deliver",
                        ],
                        [
                          "材料还要改",
                          "只记录反馈，等改好的材料确认后再投，这次不投递。",
                          "accept_revise",
                        ],
                        ["岗位不合适", "整岗结束，不再投递。", "decline"],
                      ]
                    : [
                        [
                          "接受原文",
                          "岗位合适、这份稿也行，批准当前全文，进入执行清单。",
                          "accept_original",
                        ],
                        [
                          "岗位行，稿要改",
                          "只记录反馈，等新版全文出来再单独批准发送。",
                          "accept_revise",
                        ],
                        [
                          "岗位不合适",
                          "整岗结束，这份稿不再用于发送。",
                          "decline",
                        ],
                      ]
              ).map(([label, caption, kind]) => (
                <button
                  key={kind}
                  className="choice"
                  disabled={
                    blocked || ended || !!policy.disabledDecisions?.[kind]
                  }
                  title={policy.disabledDecisions?.[kind]}
                  onClick={() =>
                    kind === "accept_revise"
                      ? setShowNote(true)
                      : void decide(kind as Decision["kind"])
                  }
                >
                  <b>{label}</b>
                  <span>{policy.disabledDecisions?.[kind] ?? caption}</span>
                </button>
              ))}
              <p className="fact" style={{ marginTop: 12 }}>
                处理并保存后这一项待办才消失；只打开看看、点关闭，都不会清掉。
              </p>
            </div>
          ) : (
            <>
              <h3>工作记录</h3>
              {d.history.length || d.decisions.length ? (
                <Points
                  values={[
                    ...d.history.map(
                      (h) => `${h.occurredAt ?? "时间未记录"} · ${h.detail}`,
                    ),
                    ...d.decisions.map(
                      (v) => `${v.createdAt} · ${v.note ?? "已保存决定"}`,
                    ),
                  ]}
                />
              ) : (
                <p className="fact">已有工作记录尚未接入，不补造历史。</p>
              )}
              <details className="material-history">
                <summary>查看材料与历史</summary>
                <GreetingSignals rank={rank} />
                {materials.isError ? (
                  <p role="alert">材料与历史读取未完成。</p>
                ) : materials.isPending ? (
                  <p role="status">读取材料中…</p>
                ) : (
                  materials.data && (
                    <>
                      {(
                        [
                          ["历版招呼语", materials.data.greetingVersions],
                          ["实际已发送", materials.data.sentGreetings],
                          ["本人决定与反馈", materials.data.feedback],
                          ["投递记录", materials.data.deliveries],
                          ["沟通原文", materials.data.commSnapshots],
                          ["同步记录", materials.data.panelSync],
                        ] as const
                      ).map(([title, items]) => (
                        <div key={title}>
                          <h3>{title}</h3>
                          <MaterialList
                            items={[...items]}
                            emptyText="该来源尚未接入或未保存。"
                          />
                        </div>
                      ))}
                    </>
                  )
                )}
              </details>
              {j.jobUrl && safeUrl(j.jobUrl) && (
                <p>
                  <a href={j.jobUrl} target="_blank" rel="noreferrer">
                    打开原始岗位
                  </a>
                </p>
              )}
              <ExecutionWorkflow detail={d} onWatch={onWatch} />
              <div className="modal-actions">
                {!ended && (
                  <button
                    className="btn primary"
                    disabled={blocked || j.blocked}
                    onClick={approval}
                  >
                    {liepin ? "批准并投递" : hasDraft ? "批准并发送" : "批准"}
                  </button>
                )}
                <span className="sp" />
                {!ended && (
                  <button
                    className="btn danger"
                    disabled={blocked}
                    onClick={() => void decide("decline")}
                  >
                    放弃岗位
                  </button>
                )}
                <button className="btn ghost" disabled={busy} onClick={close}>
                  关闭
                </button>
              </div>
            </>
          )}
          {showNote && (
            <div>
              <h3>补充意见</h3>
              <textarea
                className="greet"
                aria-label="修改意见"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={blocked}
              />
              <button
                className="btn"
                disabled={blocked || !note.trim()}
                onClick={() => void decide("accept_revise")}
              >
                保存修改意见
              </button>
            </div>
          )}
          {policy.readonlyReason && (
            <p role="status">{policy.readonlyReason}</p>
          )}
          {error && <p role="alert">{error}</p>}
          {guard && (
            <div role="alert">
              <p>修改尚未保存，关闭后不会记录。</p>
              <button className="btn" onClick={() => setGuard(false)}>
                继续编辑
              </button>
              <button className="btn" onClick={onClose}>
                放弃修改并关闭
              </button>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function CurrentExecution({
  echo,
  onClose,
  onNotice,
  onWatch,
}: {
  echo: Batch;
  onClose: () => void;
  onNotice: (s: string) => void;
  onWatch: (id: number) => void;
}) {
  const api = useMuseActions(),
    policy = useMuseConfiguration(),
    client = useQueryClient();
  const [busy, setBusy] = useState(false),
    [dispatched, setDispatched] = useState(echo.status === "executing"),
    [error, setError] = useState("");
  const status = useQuery({
    queryKey: ["batch", echo.batchId],
    queryFn: () => api.getBatch({ batchId: echo.batchId! }),
    enabled: echo.batchId != null && dispatched,
    refetchInterval: dispatched ? (policy.batchRefreshMs ?? false) : false,
  });
  function execute() {
    if (busy || dispatched || echo.batchId == null) return;
    setDispatched(true);
    onWatch(echo.batchId);
    onClose();
    void api
      .confirmExecution({ batchId: echo.batchId })
      .then((r) => {
        onNotice(r.message ?? "执行结果待核验");
        void client.invalidateQueries();
      })
      .catch(() => {
        onNotice("执行请求结果未知，请先核验，不重复执行。");
        void client.invalidateQueries();
      });
  }

  return (
    <Modal title="执行清单" wide onClose={onClose} busy={busy}>
      <h2>执行清单</h2>
      <div className="meta">
        下面是已批准、还没执行的岗位。核对完点「确认执行」，才会逐条发送或投递，并逐条回读结果。
      </div>
      <div style={{ overflowY: "auto", maxHeight: "62vh" }}>
        {echo.items.length ? (
          echo.items.map((item) => {
            const result = status.data?.items.find((r) => r.rank === item.rank);
            return (
              <div className="exec-row" key={item.rank}>
                <span>
                  <span className="t">{item.title}</span>{" "}
                  <span className="d">
                    {item.company} · <ChannelTag channel={item.platform} />
                  </span>
                </span>
                <span
                  className={result?.status === "done" ? "done-flag" : "act"}
                >
                  {result?.status === "done"
                    ? "已执行"
                    : result?.status === "failed"
                      ? "执行失败"
                      : result?.status === "unknown"
                        ? "结果待核验"
                        : dispatched
                          ? "请求已记录，等待回读"
                          : item.kind === "delivery"
                            ? "投递简历"
                            : "发送招呼"}
                </span>
                {item.greetingPreview && (
                  <details>
                    <summary>核对全文</summary>
                    <p className="preserve-lines">{item.greetingPreview}</p>
                  </details>
                )}
                {result?.detail && <p className="d">{result.detail}</p>}
              </div>
            );
          })
        ) : (
          <div className="empty">执行清单是空的。</div>
        )}
        {!!echo.excluded.length && (
          <details>
            <summary>当前不能执行的岗位</summary>
            {echo.excluded.map((e, i) => (
              <p key={i}>{e.reason}</p>
            ))}
          </details>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      {status.isError && (
        <p role="alert">结果回读未完成，请先核验，不重复执行。</p>
      )}
      <div className="modal-actions">
        <button
          className="btn primary"
          disabled={
            busy || dispatched || !echo.items.length || echo.batchId == null
          }
          onClick={() => void execute()}
        >
          {busy ? "正在提交…" : "确认执行"}
        </button>
        <button className="btn ghost" disabled={busy} onClick={onClose}>
          先不执行
        </button>
      </div>
    </Modal>
  );
}
