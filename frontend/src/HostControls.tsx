import { useState } from "react";
import { useHost, useHostOperation } from "./hostContext";
import type { HostBatch, HostChannel } from "./hostContracts";
import { JobDialog } from "./JobDialog";
import { ExecutionDialog } from "./ExecutionDialog";
import { shortTime } from "./agentReport";

function Channel({ entry }: { entry: HostChannel }) {
  const host = useHost(),
    operation = useHostOperation(`login:${entry.channel}`);
  return (
    <section>
      <h3>{entry.label}</h3>
      <p>
        {
          {
            connected: "已登录",
            dropped: "登录已掉线",
            unknown: "登录情况尚未确认",
          }[entry.status]
        }
      </p>
      <p>
        {entry.checked_at
          ? `核对于 ${shortTime(entry.checked_at)}`
          : "尚无核对时间"}
      </p>
      {entry.status === "dropped" && (
        <button
          disabled={
            !host?.source.requestLoginRestore ||
            !!entry.restore_requested_at ||
            operation.busy ||
            !!operation.pending
          }
          onClick={() =>
            void operation.run(
              () => host!.source.requestLoginRestore!(entry.channel),
              `restore:${entry.channel}`,
            )
          }
        >
          {entry.restore_requested_at ? "已请求恢复" : "请求恢复登录"}
        </button>
      )}
      {entry.restore_requested_at && (
        <p>已记录请求，等待宿主核对现有窗口后处理。</p>
      )}
      {operation.message && <p role="status">{operation.message}</p>}
      {operation.pending && (
        <button
          disabled={operation.busy || !host?.source.getOperation}
          onClick={() => void operation.verify()}
        >
          核验请求结果
        </button>
      )}
    </section>
  );
}
export function ChannelPanel({ channel }: { channel?: string }) {
  const host = useHost();
  const entries =
    host?.state.channels.filter((c) => !channel || c.channel === channel) ?? [];
  return (
    <section aria-label="渠道登录情况">
      {entries.length ? (
        entries.map((c) => <Channel key={c.channel} entry={c} />)
      ) : (
        <p>渠道登录来源尚未接入，当前登录情况未知。</p>
      )}
    </section>
  );
}
export function HostControls() {
  const host = useHost();
  const [channels, setChannels] = useState(false),
    [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState<HostBatch | null>(null),
    [message, setMessage] = useState("");
  async function prepare() {
    if (!host?.source.createExecutionBatch) return;
    setBusy(true);
    setMessage("正在生成执行清单…");
    try {
      const previous = [...host.state.batches]
        .reverse()
        .find((b) => ["ready", "executing", "unknown"].includes(b.status));
      setBatch(
        previous ??
          (await host.source.createExecutionBatch(
            host.state.jobs.map((j) => j.contact_id),
          )),
      );
      await host.refresh();
      setMessage("");
    } catch {
      setMessage("清单生成结果未确认，请刷新核对；没有发起发送。");
    } finally {
      setBusy(false);
    }
  }
  async function synchronize() {
    if (!host?.source.synchronize) return;
    setBusy(true);
    setMessage("正在核对回读与同步结果…");
    try {
      const result = await host.source.synchronize();
      await host.refresh();
      setMessage(result.message);
    } catch {
      setMessage("同步结果未知，当前显示旧记录，请先核对。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="host-toolbar" aria-label="宿主操作">
      <div className="host-buttons">
        <button onClick={() => setChannels(true)}>渠道状态</button>
        <button
          disabled={busy || !host?.source.createExecutionBatch}
          onClick={() => void prepare()}
        >
          执行清单
        </button>
        <button
          disabled={busy || !host?.source.synchronize}
          onClick={() => void synchronize()}
        >
          核对同步
        </button>
      </div>
      <p>
        {host?.state.sync.message ?? "宿主交互未接入，当前只能查看已有记录。"}
      </p>
      {!host?.source.recordDecision && (
        <p className="note">此处暂时无法保存决定或执行操作，请在对话中告知。</p>
      )}
      {message && message !== host?.state.sync.message && (
        <p role="status">{message}</p>
      )}
      {!!host?.state.sync.differences.length && (
        <ul>
          {host.state.sync.differences.map((d) => (
            <li key={d.job_id}>
              {d.title}：{d.detail}
            </li>
          ))}
        </ul>
      )}
      {channels && (
        <JobDialog title="渠道状态" onClose={() => setChannels(false)}>
          <ChannelPanel />
        </JobDialog>
      )}
      {batch && (
        <ExecutionDialog initialBatch={batch} onClose={() => setBatch(null)} />
      )}
    </section>
  );
}
