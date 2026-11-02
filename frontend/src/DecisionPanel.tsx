import { useEffect, useState } from "react";
import type { JobView } from "./contracts";
import type { HostDecisionRequest, HostMaterial } from "./hostContracts";
import {
  currentMaterial,
  latestDecision,
  safeMaterialUrl,
} from "./hostService";
import { useHost, useHostOperation } from "./hostContext";
import { channelOf } from "./channels";

export function MaterialView({ material }: { material: HostMaterial }) {
  return (
    <section className="host-material">
      <h4>{material.label}</h4>
      <p className="jq-exact">{material.body || "本项没有消息正文。"}</p>
      {material.attachments.length ? (
        <ul>
          {material.attachments.map((a) => {
            const url = safeMaterialUrl(a.url);
            return (
              <li key={a.digest}>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer">
                    打开 {a.name}
                  </a>
                ) : (
                  `${a.name}：文件暂时无法打开`
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="note">本份材料未附文件。</p>
      )}
    </section>
  );
}

export function DecisionPanel({ job }: { job: JobView }) {
  const host = useHost();
  const entry = host?.state.jobs.find(
    (j) => j.job_id === job.job.job_id && j.contact_id === job.job.pipeline_id,
  );
  const material = entry && currentMaterial(entry);
  const operation = useHostOperation(String(job.job.pipeline_id));
  const [body, setBody] = useState(material?.body ?? "");
  const [note, setNote] = useState("");
  useEffect(() => {
    setBody(material?.body ?? "");
  }, [material?.revision]);
  const disabled =
    !host?.source.recordDecision ||
    !material ||
    operation.busy ||
    !!operation.pending;
  const decision = entry && latestDecision(entry);
  const approved =
    decision?.kind === "approve_material" &&
    decision.material?.revision === material?.revision;
  const edited = body !== material?.body;
  function decide(kind: HostDecisionRequest["kind"]) {
    if (!host?.source.recordDecision || !entry || !material) return;
    void operation.run((key) =>
      host.source.recordDecision!({
        candidate_id: host.state.candidate_id,
        job_id: entry.job_id,
        contact_id: entry.contact_id,
        operation_key: key,
        material_revision: material.revision,
        kind,
        body,
        attachment_digests: material.attachments.map((a) => a.digest),
        note,
        todo_id: null,
        option_id: null,
      }),
    );
  }
  return (
    <section className="host-decisions" aria-label="材料与本人决定">
      <h3>材料与本人决定</h3>
      {!material && <p>材料写入尚未接入，无法在面板内保存，请在对话中告知。</p>}
      {approved && <p>已记录材料批准，尚未执行</p>}
      {decision?.kind === "decline" && (
        <p>已记录放弃决定，等待业务服务处理。</p>
      )}
      {material && <MaterialView material={material} />}
      {channelOf(job).greetings && (
        <label>
          材料正文
          <textarea
            aria-label="材料正文"
            value={body}
            disabled={disabled}
            onChange={(e) => setBody(e.target.value)}
            rows={5}
          />
        </label>
      )}
      <label>
        决定备注
        <textarea
          aria-label="决定备注"
          value={note}
          disabled={disabled}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
        />
      </label>
      {edited && <p>正文已修改，请先保存草稿，再审阅并批准新版。</p>}
      <div className="host-buttons">
        {channelOf(job).greetings && (
          <>
            <button
              disabled={disabled || !edited}
              onClick={() => decide("save_draft")}
            >
              保存草稿
            </button>
            <button
              disabled={disabled || edited}
              onClick={() => decide("approve_text")}
            >
              这版文案可以
            </button>
          </>
        )}
        <button
          disabled={disabled || edited || approved}
          onClick={() => decide("approve_material")}
        >
          批准这份材料
        </button>
        <button
          disabled={disabled || edited || decision?.kind === "decline"}
          onClick={() => decide("decline")}
        >
          放弃这个岗位
        </button>
      </div>
      <p className="note">
        保存决定后仍需核对具体执行项目；文案意见、材料批准与实际发送分别记录。
      </p>
      {operation.message && <p role="status">{operation.message}</p>}
      {operation.pending && (
        <button
          disabled={operation.busy || !host?.source.getOperation}
          onClick={() => void operation.verify()}
        >
          核验保存结果
        </button>
      )}
    </section>
  );
}
