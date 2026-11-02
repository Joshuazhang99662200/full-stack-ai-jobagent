import { useState, type ReactNode } from "react";
import { text, type JobView, type Snapshot } from "./contracts";
import { channelOf } from "./channels";
import { belongs, label, stages, type Report } from "./agentReport";
import { JobWorkflow } from "./JobWorkflow";
import { DecisionPanel, MaterialView } from "./DecisionPanel";
import { TodoPanel } from "./TodoPanel";
import { ChannelPanel } from "./HostControls";
import { useHost } from "./hostContext";

const raw = (value: unknown) => <pre>{JSON.stringify(value, null, 2)}</pre>;
export function JobDetailTabs({
  job,
  rounds,
  ambiguous,
  item,
  snapshot,
  progress,
  renderJobDetails,
  initialTab = "progress",
}: {
  job: JobView;
  rounds: JobView[];
  ambiguous: boolean;
  item: Report;
  snapshot: Snapshot;
  progress: ReactNode;
  renderJobDetails: (job: JobView) => ReactNode;
  initialTab?: string;
}) {
  const [tab, setTab] = useState(initialTab);
  const [more, setMore] = useState(false);
  const host = useHost();
  const hostJob = host?.state.jobs.find(
    (j) => j.job_id === job.job.job_id && j.contact_id === job.job.pipeline_id,
  );
  const hostJobs =
    host?.state.jobs.filter((j) =>
      rounds.some(
        (r) => r.job.job_id === j.job_id && r.job.pipeline_id === j.contact_id,
      ),
    ) ?? [];
  const channel = channelOf(job);
  const tabs = [
    ["progress", "进展与操作"],
    ["materials", channel.greetings ? "招呼与材料" : "投递与材料"],
    ["history", "历史记录"],
    ["todo", "需要你决定"],
    ["channel", "渠道与流程"],
    ...(more
      ? [
          ["signals", "Signal / Harness"],
          ["raw", "排查问题"],
        ]
      : []),
  ];
  const originalWork = stages(snapshot).filter((stage) =>
    rounds.some((round) => belongs(stage, round)),
  );
  const runIds = new Set(originalWork.map((stage) => stage.runId));
  const runs = snapshot.runs.filter((entry) =>
    runIds.has(text(entry.run.run_id)),
  );
  return (
    <>
      <p className="note">
        {text(job.job.company)} / {channel.name}
      </p>
      <p>
        薪资：<strong>{text(job.job.salary_raw)}</strong>
      </p>
      <button aria-expanded={more} onClick={() => setMore(!more)}>
        更多
      </button>
      <nav className="jq-dialog-tabs" role="tablist" aria-label="岗位详情内容">
        {tabs.map(([id, name]) => (
          <button
            key={id}
            id={`detail-tab-${id}`}
            role="tab"
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            aria-controls="job-detail-panel"
            onKeyDown={(event) => {
              if (
                !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
              )
                return;
              event.preventDefault();
              const index = tabs.findIndex(([key]) => key === id);
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? tabs.length - 1
                    : (index +
                        (event.key === "ArrowRight" ? 1 : -1) +
                        tabs.length) %
                      tabs.length;
              setTab(tabs[next][0]);
              document.getElementById(`detail-tab-${tabs[next][0]}`)?.focus();
            }}
            onClick={() => setTab(id)}
          >
            {name}
          </button>
        ))}
      </nav>
      <div
        id="job-detail-panel"
        role="tabpanel"
        aria-labelledby={`detail-tab-${tab}`}
      >
        {tab === "progress" && (
          <>
            {progress}
            <DecisionPanel job={job} />
          </>
        )}
        {tab === "todo" && <TodoPanel contactId={text(job.job.pipeline_id)} />}
        {tab === "channel" && <ChannelPanel channel={channel.name} />}
        {tab === "materials" && (
          <section className="jq-materials">
            {!channel.greetings && (
              <p className="notice">
                {channel.known
                  ? "按当前渠道的接口能力核对投递材料；实际投递和附件传输条件仍需检查。"
                  : "渠道能力尚未接入，请先核对来源。"}
              </p>
            )}
            <h3>岗位正文</h3>
            <p className="jq-exact">{text(job.job.jd_text)}</p>
            {channel.greetings && (
              <>
                <h3>当前草稿</h3>
                <p className="jq-exact">{text(job.job.draft_greeting)}</p>
                <p>当前草稿，是否适用请核对已保存的材料。</p>
                <h3>保留的获批正文</h3>
                <p className="jq-exact">{text(job.job.approved_greeting)}</p>
                <h3>保留的实际发送正文</h3>
                <p className="jq-exact">{text(job.job.sent_greeting)}</p>
                <p className="note">
                  是否可执行须由审批服务核对准确正文、附件和当前版本。
                </p>
              </>
            )}
            {hostJob?.materials.map((material) => (
              <MaterialView key={material.revision} material={material} />
            ))}
            {!hostJob?.materials.some((m) => m.attachments.length) && (
              <p>
                实际简历文件来源尚未接入；已有引用保留在“更多 →
                排查问题”中，不能确认附件内容。
              </p>
            )}
            <p className="note">
              材料决定在“进展与操作”中保存；是否可执行须由业务服务核对。
            </p>
          </section>
        )}
        {tab === "history" && (
          <>
            {hostJobs.map((historyJob) => (
              <section key={historyJob.contact_id}>
                <h3>历版材料</h3>
                {historyJob.materials.map((material) => (
                  <MaterialView key={material.revision} material={material} />
                ))}
                <h3>本人决定与执行记录</h3>
                {historyJob.events.length ? (
                  <ol className="history">
                    {historyJob.events.map((event) => (
                      <li key={event.event_id}>
                        <time>
                          {new Date(event.occurred_at).toLocaleString("zh-CN")}
                        </time>
                        <strong>
                          {(
                            {
                              save_draft: "保存草稿",
                              approve_text: "文案意见已记录",
                              approve_material: "材料批准已记录",
                              decline: "放弃决定已记录",
                              answer_todo: "待办决定已记录",
                              execution_readback: "执行回读",
                            } as Record<string, string>
                          )[event.kind] ?? "已保存工作记录"}
                        </strong>
                        <p>{event.detail}</p>
                        {event.material && (
                          <MaterialView material={event.material} />
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p>尚无面板决定或执行记录。</p>
                )}
              </section>
            ))}
            {rounds
              .filter((round) => round.job.pipeline_id !== job.job.pipeline_id)
              .map((round, index) => (
                <section key={text(round.job.pipeline_id)}>
                  <h3>此前联系记录 {index + 1}</h3>
                  <p>{label(round.job.pipeline_state)}</p>
                  <h4>保留的实际发送正文</h4>
                  <p className="jq-exact">{text(round.job.sent_greeting)}</p>
                  <h4>保留的获批正文</h4>
                  <p className="jq-exact">
                    {text(round.job.approved_greeting)}
                  </p>
                  <ol className="history">
                    {round.history.map((event, i) => (
                      <li key={i}>
                        <time>
                          {typeof event.changed_at === "string"
                            ? new Date(event.changed_at).toLocaleString("zh-CN")
                            : "时间未记录"}
                        </time>
                        <strong>{label(event.to_state)}</strong>
                      </li>
                    ))}
                  </ol>
                </section>
              ))}
            {channel.greetings && !ambiguous ? (
              renderJobDetails(job)
            ) : (
              <>
                <h3>投递与沟通进展</h3>
                <p>
                  {["draft_pending", "greeting_sent", "greeting_read"].includes(
                    text(job.job.pipeline_state),
                  )
                    ? "当前历史状态需按渠道核对，原始值保留在原始记录中。"
                    : label(job.job.pipeline_state)}
                </p>
                <p>
                  现有历史记录：{job.history.length}{" "}
                  条，具体来源与原文可在原始记录中核对。
                </p>
              </>
            )}
          </>
        )}
        {tab === "signals" && (
          <>
            <h3>Signal</h3>
            <p>Signal 尚未接入当前岗位查询，无法确认反馈是否已被策略采用。</p>
            <h3>Harness 运行与产物</h3>
            {runs.length ? (
              runs.map((entry) => (
                <section key={text(entry.run.run_id)}>
                  <h4>{text(entry.run.run_id)}</h4>
                  <p>
                    运行状态：{text(entry.run.phase)}；记录状态：
                    {entry.freshness}
                  </p>
                  {raw(entry.run.artifacts ?? [])}
                </section>
              ))
            ) : (
              <p>未找到明确关联该岗位的运行记录。</p>
            )}
            <p className="note">
              关联依据是已登记的岗位编号；运行记录不证明审批或发送已完成。
            </p>
          </>
        )}
        {tab === "raw" && (
          <>
            <p className="note">
              以下是查询接口返回的完整记录。未返回的 SQL
              表、字段和关联尚未接入，不补造。
            </p>
            <h3>岗位、元数据与历史</h3>
            {raw(job)}
            <details>
              <summary>历次联系记录（{rounds.length}）</summary>
              {raw(rounds)}
            </details>
            <h3>已关联工作</h3>
            {raw(originalWork.map((stage) => stage.event))}
            <h3>来源读取情况</h3>
            {raw(snapshot.sources)}
            <h3>宿主交互原始记录</h3>
            {raw(hostJob ?? null)}
          </>
        )}
      </div>
      <JobWorkflow item={item} greetings={channel.greetings} />
    </>
  );
}
