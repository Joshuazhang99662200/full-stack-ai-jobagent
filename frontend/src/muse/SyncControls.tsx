import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMuseActions, useMuseConfiguration } from "./context";
import type { MuseGetJobResponse } from "./contracts";
import { ChannelTag } from "./ChannelTag";

export function useSelectionQueue() {
  const api = useMuseActions();
  return useQuery({
    queryKey: ["selection-queue"],
    queryFn: () => api.getSelectionQueue({}),
  });
}
export function SelectionQueueBar({
  visibleRanks,
  onWatch,
}: {
  visibleRanks: number[];
  onWatch: (id: number, excluded?: number) => void;
}) {
  const api = useMuseActions(),
    policy = useMuseConfiguration(),
    client = useQueryClient(),
    queue = useSelectionQueue();
  const [message, setMessage] = useState("");
  const operation = useMutation({
    mutationFn: api.applySelectionOperation,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["selection-queue"] });
    },
    onError: () => setMessage("选择保存未确认，请先重新读取，不自动重试。"),
  });
  const execute = useMutation({
    mutationFn: () => api.executeSelectionDirect({}),
    onSuccess: (r) => {
      setMessage(r.message ?? "执行请求待核验");
      if (r.batchId != null) onWatch(r.batchId, r.excluded.length);
      void client.invalidateQueries();
    },
    onError: () => setMessage("执行请求结果未知，请先核验，不要重复提交。"),
  });
  return (
    <section className="selection-bar" aria-label="选择队列与一键投递">
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
        }}
      >
        <b
          role="status"
          style={{ fontWeight: 600 }}
        >{`已选 ${queue.data?.count ?? "?"} 个岗位`}</b>
        {(
          [
            ["select_visible", "全选", "全选当前列表"],
            ["invert_visible", "反选", "反选当前列表"],
            ["clear_visible", "取消选择", "取消当前列表的选择"],
            ["clear_all", "清空", "清空全部选择"],
          ] as const
        ).map(([op, label, aria]) => (
          <button
            key={op}
            className="ctl"
            aria-label={aria}
            disabled={
              !queue.data ||
              operation.isPending ||
              execute.isPending ||
              (op !== "clear_all" && !visibleRanks.length)
            }
            onClick={() =>
              operation.mutate({
                operation: op,
                visibleRanks: op === "clear_all" ? [] : visibleRanks,
              })
            }
          >
            {label}
          </button>
        ))}
        <button
          className="ctl primary"
          disabled={
            !queue.data?.count ||
            operation.isPending ||
            execute.isPending ||
            policy.quickExecutionAvailable === false
          }
          onClick={() => execute.mutate()}
        >
          {execute.isPending
            ? "正在提交请求…"
            : `一键投递（已选 ${queue.data?.count ?? 0} 条）`}
        </button>
      </div>
      <p className="fact">
        只执行当前准确正文及附件已获批准的岗位；未批准、被屏蔽、已执行或结果未知的岗位保留在已选队列。成功按逐项回读确认。
      </p>
      {policy.quickExecutionAvailable === false && (
        <p className="fact">快捷执行服务尚未接入。</p>
      )}
      {queue.isError && (
        <p className="fact">服务端选择队列尚未接入，选择和快捷执行暂不可用。</p>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
export function SelectionCheckbox({
  rank,
  title,
}: {
  rank: number;
  title: string;
}) {
  const api = useMuseActions(),
    client = useQueryClient(),
    q = useSelectionQueue();
  const [error, setError] = useState("");
  const toggle = useMutation({
    mutationFn: api.toggleSelectionItem,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["selection-queue"] });
    },
    onError: () => setError("选择保存未确认，请重新读取"),
  });
  return (
    <div
      className="cell selection-cell"
      data-label="选择"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        type="checkbox"
        aria-label={`选择岗位：${title}`}
        checked={q.data?.ranks.includes(rank) ?? false}
        disabled={!q.data || toggle.isPending}
        onChange={(e) => toggle.mutate({ rank, selected: e.target.checked })}
      />
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
export function RegenerateGreetingControl({
  rank,
  text,
  onSaved,
  previousText,
  disabled,
  onBusy = () => {},
  onUnknown = () => {},
}: {
  rank: number;
  text: string;
  previousText: string;
  onSaved: () => void;
  disabled: boolean;
  onBusy?: (v: boolean) => void;
  onUnknown?: () => void;
}) {
  const api = useMuseActions(),
    policy = useMuseConfiguration(),
    client = useQueryClient();
  const [message, setMessage] = useState("");
  const [unknown, setUnknown] = useState(false);
  useEffect(() => {
    if (unknown) onUnknown();
  }, [unknown]);
  const regenerate = useMutation({
    onMutate: () => onBusy(true),
    onSettled: () => onBusy(false),
    mutationFn: () => api.regenerateGreeting({ rank, currentText: text }),
    onSuccess: async (r) => {
      if (!r.ok || !r.greeting) {
        setMessage(r.message ?? "生成结果待核验");
        if (r.error === "outcome_unknown") setUnknown(true);
        return;
      }
      try {
        const fresh = await api.getJob({ rank });
        if (fresh.draftGreeting !== r.greeting) {
          setUnknown(true);
          setMessage("新稿保存结果尚未核实，请先核验。");
          return;
        }
        const signals = await api.getGreetingSignals({ rank });
        if (
          !signals.signals.some(
            (s) =>
              s.kind === "ai_regenerate" &&
              s.afterText === r.greeting &&
              s.beforeText === text,
          )
        ) {
          setUnknown(true);
          setMessage("新稿已读取，改前/改后记录尚未核实。");
          return;
        }
        onSaved();
        setMessage(
          "新版全文已保存，仍是拟发送，需重新审阅。旧版保留在材料与历史。",
        );
        await client.invalidateQueries();
      } catch {
        setUnknown(true);
        setMessage("生成保存结果待核验，不重复提交。");
      }
    },
    onError: () => {
      setUnknown(true);
      setMessage("生成结果未知，请先核验，不重复提交。");
    },
  });
  const save = useMutation({
    onMutate: () => onBusy(true),
    onSettled: () => onBusy(false),
    mutationFn: () => api.saveGreetingDraft({ rank, text }),
    onSuccess: async (r) => {
      if (!r.ok) {
        setMessage(r.message ?? "修改保存未确认");
        if (r.error === "outcome_unknown") setUnknown(true);
        return;
      }
      try {
        const fresh = await api.getJob({ rank });
        if (fresh.draftGreeting !== text) {
          setUnknown(true);
          setMessage("修改回读不一致，请先核验。");
          return;
        }
        const audit = await api.getGreetingSignals({ rank });
        if (
          text !== previousText &&
          !audit.signals.some(
            (signal) =>
              signal.beforeText === previousText && signal.afterText === text,
          )
        ) {
          setUnknown(true);
          setMessage("正文已读取，改前/改后记录尚未核实。");
          return;
        }
        onSaved();
        setMessage("修改已保存，旧版及改前/改后全文保留。");
        await client.invalidateQueries();
      } catch {
        setUnknown(true);
        setMessage("修改回读未完成，请先核验。");
      }
    },
    onError: () => {
      setUnknown(true);
      setMessage("修改结果未知，请先核验。");
    },
  });
  return (
    <div>
      <div className="btnrow">
        <button
          className="btn"
          aria-label="重新生成招呼语"
          disabled={
            disabled ||
            policy.regenerationAvailable === false ||
            regenerate.isPending ||
            save.isPending ||
            unknown
          }
          onClick={() => regenerate.mutate()}
        >
          {regenerate.isPending ? "正在重新生成…" : "重新生成"}
        </button>
        <button
          className="btn"
          aria-label="保存招呼语修改"
          disabled={
            disabled || regenerate.isPending || save.isPending || unknown
          }
          onClick={() => save.mutate()}
        >
          保存修改
        </button>
      </div>
      {policy.regenerationAvailable === false && (
        <p className="fact">重新生成服务尚未接入</p>
      )}
      {message && <p role={unknown ? "alert" : "status"}>{message}</p>}
    </div>
  );
}
export function GreetingSignals({ rank }: { rank: number }) {
  const api = useMuseActions();
  const signals = useQuery({
    queryKey: ["greeting-signals", rank],
    queryFn: () => api.getGreetingSignals({ rank }),
  });
  return (
    <section aria-label="招呼语改写记录">
      <h3>招呼语改写记录</h3>
      {signals.isError ? (
        <p>改写记录来源读取未完成。</p>
      ) : signals.data?.signals.length ? (
        signals.data.signals.map((s) => (
          <details key={s.id}>
            <summary>
              {s.kind === "ai_regenerate" ? "AI 重新生成" : "手动修改"} ·{" "}
              {s.createdAt}
            </summary>
            <h4>改前全文</h4>
            <p className="preserve-lines">{s.beforeText ?? "此前没有稿件"}</p>
            <h4>改后全文</h4>
            <p className="preserve-lines">{s.afterText}</p>
          </details>
        ))
      ) : (
        <p className="fact">当前未读取到改写记录。</p>
      )}
    </section>
  );
}
export function ExecutionWorkflow({
  detail,
  onWatch,
}: {
  detail: MuseGetJobResponse;
  onWatch: (id: number, excluded?: number) => void;
}) {
  const api = useMuseActions(),
    policy = useMuseConfiguration(),
    client = useQueryClient();
  const approval = useQuery({
    queryKey: ["exec-precheck", detail.job?.rank],
    queryFn: () => api.getExecPrecheck({ rank: detail.job!.rank }),
    enabled: !!detail.job,
  });
  const [message, setMessage] = useState("");
  const state = detail.job?.state,
    fail = detail.execFailures;
  const retry = useMutation({
    mutationFn: () => api.executeJobDirect({ rank: detail.job!.rank }),
    onSuccess: (r) => {
      setMessage(r.message ?? "请求待核验");
      if (r.batchId != null) onWatch(r.batchId);
      void client.invalidateQueries();
    },
    onError: () => setMessage("再次执行请求结果未知，请先核验。"),
  });
  const known =
    state === "sent" || state === "delivered"
      ? "done"
      : state === "exec_failed"
        ? "failed"
        : state === "executing"
          ? "executing"
          : state === "exec_unknown"
            ? "unknown"
            : "pending";
  return (
    <section
      aria-label="执行流程"
      className={`execution-workflow outcome-${known}`}
    >
      <h3>执行与回读</h3>
      <ol
        aria-label="工作流程"
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        {[
          {
            label: "匹配核对",
            done: detail.history.some((h) => h.eventKind === "match_computed"),
          },
          { label: "准备材料", done: !!detail.draftGreeting },
          {
            label: "材料批准",
            done: approval.data?.approved === true,
          },
          { label: "执行回读", done: known === "done" },
        ].map((step, index) => (
          <li
            key={step.label}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 12,
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: 9,
                height: 9,
                borderRadius: "50%",
                display: "inline-block",
                background:
                  index === 3 && known === "failed"
                    ? "var(--red)"
                    : step.done
                      ? "var(--blue)"
                      : "transparent",
                border:
                  index === 3 && known === "executing"
                    ? "2px solid var(--blue)"
                    : "1px solid var(--line-2)",
              }}
            />
            {step.label}
          </li>
        ))}
      </ol>
      <p>
        {known === "done"
          ? "成功（已回读确认）"
          : known === "failed"
            ? `执行失败：${detail.job?.execFailureReason ?? fail.lastReason ?? "原因尚未接入"}`
            : known === "executing"
              ? "执行中，等待逐条回读"
              : known === "unknown"
                ? "执行结果未知，先核验，不重复执行"
                : "尚未读取到本轮执行结果"}
      </p>
      {fail.jobCount > 0 && (
        <p className="fact">
          本岗位累计失败 {fail.jobCount} 次，
          <ChannelTag channel={fail.channel} /> 渠道累计 {fail.channelCount}{" "}
          次；最近：{fail.lastReason}（{fail.lastAt ?? "时间未记录"}）
        </p>
      )}
      {known === "failed" && (
        <button
          className="btn"
          disabled={retry.isPending || policy.retryAvailable === false}
          onClick={() => retry.mutate()}
        >
          再次执行
        </button>
      )}
      {known === "failed" && policy.retryAvailable === false && (
        <p className="fact">再次执行服务尚未接入。</p>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
export function ExecutionProgress({
  batchId,
  excludedCount = 0,
  onClose,
}: {
  batchId: number;
  excludedCount?: number;
  onClose: () => void;
}) {
  const api = useMuseActions(),
    policy = useMuseConfiguration();
  const q = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => api.getBatch({ batchId }),
    refetchInterval: policy.batchRefreshMs ?? false,
  });
  const batch = q.data,
    items = batch?.items ?? [],
    running = items.some((i) => ["queued", "running"].includes(i.status));
  return (
    <section aria-label="执行进度" className="selection-bar">
      <h3>执行进度</h3>
      {q.isError ? (
        <p role="alert">执行回读未完成，先核验，不重复执行。</p>
      ) : !batch?.batch ? (
        <p>正在核验执行请求…</p>
      ) : (
        <>
          <p>
            成功 {items.filter((i) => i.status === "done").length} 条、失败{" "}
            {items.filter((i) => i.status === "failed").length} 条、待核验{" "}
            {items.filter((i) => !["done", "failed"].includes(i.status)).length}{" "}
            条、拦下 {excludedCount} 条。逐条结果见各岗位进展。
          </p>
          {running && (
            <ul>
              {items.map((i) => (
                <li key={i.rank}>
                  {i.title} · <ChannelTag channel={i.platform} /> ·{" "}
                  {i.status === "done"
                    ? "回读已完成"
                    : i.status === "failed"
                      ? i.detail
                      : "等待回读"}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className="btnrow">
        <button className="ctl" onClick={() => void q.refetch()}>
          核验执行进展
        </button>
        <button className="ctl" onClick={onClose}>
          关闭执行进度显示
        </button>
      </div>
    </section>
  );
}
