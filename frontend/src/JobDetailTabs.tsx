import { useState, type ReactNode } from "react";
import { text, type JobView, type Snapshot } from "./contracts";
import { channelOf } from "./channels";
import { belongs, label, stages, type Report } from "./agentReport";
import { JobWorkflow } from "./JobWorkflow";

const raw = (value: unknown) => <pre>{JSON.stringify(value, null, 2)}</pre>;
export function JobDetailTabs({
  job,
  rounds,
  ambiguous,
  item,
  snapshot,
  progress,
  renderJobDetails,
}: {
  job: JobView;
  rounds: JobView[];
  ambiguous: boolean;
  item: Report;
  snapshot: Snapshot;
  progress: ReactNode;
  renderJobDetails: (job: JobView) => ReactNode;
}) {
  const [tab, setTab] = useState("progress");
  const channel = channelOf(job);
  const tabs = [
    ["progress", "进展与操作"],
    ["materials", channel.greetings ? "招呼与材料" : "投递与材料"],
    ["history", "历史记录"],
    ["signals", "Signal / Harness"],
    ["raw", "原始记录"],
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
        {tab === "progress" && progress}
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
                <p>草稿版本：{text(job.job.draft_version)}</p>
                <h3>保留的获批正文</h3>
                <p className="jq-exact">{text(job.job.approved_greeting)}</p>
                <p className="note">
                  是否可执行须由审批服务核对准确正文、附件和当前版本。
                </p>
              </>
            )}
            <h3>简历与附件</h3>
            <dl className="facts">
              <div>
                <dt>文件引用</dt>
                <dd>{text(job.job.resume_file_id)}</dd>
              </div>
              <div>
                <dt>简历版本</dt>
                <dd>{text(job.job.resume_version)}</dd>
              </div>
            </dl>
            <p className="note">
              审批、放弃和投递的写入接口尚未接入此页面；当前可查看记录。
            </p>
          </section>
        )}
        {tab === "history" && (
          <>
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
          </>
        )}
      </div>
      <JobWorkflow item={item} greetings={channel.greetings} />
    </>
  );
}
