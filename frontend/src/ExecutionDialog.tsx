import { useState } from "react";
import type { HostBatch } from "./hostContracts";
import { useHost, useHostOperation } from "./hostContext";
import { JobDialog } from "./JobDialog";
import { MaterialView } from "./DecisionPanel";

const names = {
  queued: "尚未执行",
  running: "执行中，等待逐条回读",
  verified: "回读已核验",
  failed: "执行失败",
  unknown: "结果未知，请先核验",
};
export function ExecutionDialog({
  initialBatch,
  onClose,
}: {
  initialBatch: HostBatch;
  onClose(): void;
}) {
  const host = useHost();
  const batch =
    host?.state.batches.find((b) => b.batch_id === initialBatch.batch_id) ??
    initialBatch;
  const [selected, setSelected] = useState<string[]>([]);
  const operation = useHostOperation(`batch:${batch.batch_id}`);
  const items = batch.items.filter((i) => selected.includes(i.item_id));
  const ready = batch.status === "ready";
  return (
    <JobDialog title="逐项核对执行清单" onClose={onClose}>
      <p>只执行你明确勾选并确认的项目。请核对以下全文、材料版本和实际附件。</p>
      {host?.source.mode === "demo" && (
        <p className="notice">合成演示：不会联系真实招聘方。</p>
      )}
      {batch.items.map((item) => (
        <article key={item.item_id} className="host-exec-item">
          <label>
            <input
              type="checkbox"
              aria-label={`选择 ${item.title}`}
              checked={selected.includes(item.item_id)}
              disabled={!ready || operation.busy || !!operation.pending}
              onChange={(e) =>
                setSelected(
                  e.target.checked
                    ? [...selected, item.item_id]
                    : selected.filter((i) => i !== item.item_id),
                )
              }
            />
            {item.title} · {item.channel}
          </label>
          <MaterialView material={item.material} />
          <p>
            {!ready && !item.selected
              ? "未选择，本次没有执行"
              : item.status === "verified" && host?.source.mode === "demo"
                ? "合成回读已核验"
                : names[item.status]}
          </p>
          {item.readback && <p>{item.readback.detail}</p>}
        </article>
      ))}
      {!batch.items.length && <p>没有通过执行前检查的项目。</p>}
      {batch.excluded.length > 0 && (
        <section>
          <h3>暂不能执行</h3>
          <ul>
            {batch.excluded.map((item, i) => (
              <li key={i}>
                {host?.state.jobs
                  .find((j) => j.job_id === item.job_id)
                  ?.materials.at(-1)?.label ?? "待核对岗位"}
                ：{item.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
      <p>本次已选择 {items.length} 项。</p>
      <button
        disabled={
          !host?.source.confirmExecution ||
          !ready ||
          !items.length ||
          operation.busy ||
          !!operation.pending
        }
        onClick={() =>
          void operation.run((key) =>
            host!.source.confirmExecution!({
              candidate_id: host!.state.candidate_id,
              operation_key: key,
              batch_id: batch.batch_id,
              selected: items.map((item) => ({
                item_id: item.item_id,
                material_revision: item.material.revision,
                body: item.material.body,
                attachment_digests: item.material.attachments.map(
                  (a) => a.digest,
                ),
              })),
            }),
          )
        }
      >
        确认执行所选项目
      </button>
      {!host?.source.confirmExecution && (
        <p>当前未接入执行服务，不能在面板内发送或投递，请在对话中告知。</p>
      )}
      {operation.message && <p role="status">{operation.message}</p>}
      {operation.pending && (
        <button
          disabled={operation.busy || !host?.source.getOperation}
          onClick={() => void operation.verify()}
        >
          核验执行结果
        </button>
      )}
    </JobDialog>
  );
}
