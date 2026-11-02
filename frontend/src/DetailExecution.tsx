import { useRef, useState } from "react";
import type { JobView } from "./contracts";
import type { HostBatch } from "./hostContracts";
import { channelOf } from "./channels";
import { useHost } from "./hostContext";
import { ExecutionDialog } from "./ExecutionDialog";

/** Opening a scoped checklist prepares a plan; it never confirms execution. */
export function DetailExecution({
  job,
  changed,
}: {
  job: JobView;
  changed: boolean;
}) {
  const host = useHost();
  const opener = useRef<HTMLButtonElement>(null);
  const [batch, setBatch] = useState<HostBatch | null>(null);
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const connected =
    !!host?.source.createExecutionBatch && !!host?.source.confirmExecution;
  async function prepare() {
    if (!connected || !host || busy || changed) return;
    setBusy(true);
    setMessage("正在核对这个岗位的材料和执行条件…");
    try {
      const contact = String(job.job.pipeline_id);
      const materialRevision = host.state.jobs
        .find((j) => j.contact_id === contact)
        ?.materials.at(-1)?.revision;
      const previous = [...host.state.batches]
        .reverse()
        .find(
          (b) =>
            ["ready", "executing", "unknown"].includes(b.status) &&
            b.items.length === 1 &&
            b.items[0].contact_id === contact &&
            (b.status !== "ready" ||
              b.items[0].material.revision === materialRevision),
        );
      const next = previous
        ? await host.source.getBatch(previous.batch_id)
        : await host.source.createExecutionBatch!([contact]);
      if (
        !next ||
        next.items.some(
          (i) => i.contact_id !== contact || i.job_id !== job.job.job_id,
        )
      )
        throw new Error("scope");
      setBatch(next);
      await host.refresh();
      setMessage("");
    } catch {
      setMessage("清单准备结果未确认，请刷新核对；没有发起发送或投递。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="host-detail-execution">
      <button
        ref={opener}
        disabled={!connected || busy || changed}
        onClick={() => void prepare()}
      >
        {channelOf(job).greetings ? "审批并发送" : "审批并投递"}
      </button>
      <p className="note">先打开本岗位执行清单，再逐项审阅和确认。</p>
      {!connected && (
        <p>当前未接入执行服务，不能在面板内发送或投递，请在对话中告知。</p>
      )}
      {message && <p role="status">{message}</p>}
      {batch && (
        <ExecutionDialog
          initialBatch={batch}
          onClose={() => {
            setBatch(null);
            requestAnimationFrame(() =>
              opener.current?.focus({ preventScroll: true }),
            );
          }}
        />
      )}
    </section>
  );
}
