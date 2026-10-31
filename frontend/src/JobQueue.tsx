import { useState, type ReactNode } from "react";
import { text, type JobView, type Snapshot } from "./contracts";
import {
  closed,
  contactGroups,
  filterOf,
  label,
  report,
  scoreOf,
  shortTime,
  stages,
  type Lane,
  type Report,
  type Stage,
} from "./agentReport";

const laneOrder: Record<Lane, number> = {
  needs: 0,
  active: 1,
  waiting: 2,
  idle: 3,
  closed: 4,
};
const laneNames: [Lane, string][] = [
  ["active", "正在推进"],
  ["needs", "需要你"],
  ["waiting", "等待对方"],
];
const filterNames: Record<string, string> = {
  pass: "通过",
  review: "待核对",
  reject: "不通过",
};
function rank(a: JobView, b: JobView) {
  const ranks: Record<string, number> = { pass: 0, review: 1, reject: 3 };
  return (
    (ranks[text(filterOf(a)?.decision)] ?? 2) -
      (ranks[text(filterOf(b)?.decision)] ?? 2) ||
    (scoreOf(b) ?? -Infinity) - (scoreOf(a) ?? -Infinity) ||
    0
  );
}
const unique = (items: Stage[]) => [
  ...new Set(items.map((stage) => label(stage.event.activity))),
];
function Progress({ item }: { item: Report }) {
  const done = unique(item.done);
  return (
    <ol className="jq-flow" aria-label="工作进展">
      {done.length > 0 && (
        <li className="done">已{done.slice(-3).join("、")}</li>
      )}
      {item.failed.map((stage) => (
        <li className="failed" key={stage.key}>
          {label(stage.event.activity)}失败
        </li>
      ))}
      {item.unconfirmed.map((stage) => (
        <li className="unconfirmed" key={stage.key}>
          {label(stage.event.activity)}：状态未确认
        </li>
      ))}
      {unique(item.current).map((name) => (
        <li className="current" key={name}>
          正在{name}
        </li>
      ))}
      {item.lane !== "closed" && (
        <li className="next">
          {item.next ? `接下来：${item.next}` : "下一步尚未安排"}
        </li>
      )}
    </ol>
  );
}
export function JobQueue({
  snapshot,
  renderJobDetails,
  onTrace,
}: {
  snapshot: Snapshot;
  renderJobDetails: (job: JobView) => ReactNode;
  onTrace: (runId: string) => void;
}) {
  const all = stages(snapshot);
  const rows = contactGroups(snapshot.jobs)
    .map((group) => ({
      group,
      job: group.representative,
      item: report(group.representative, group, all),
    }))
    .sort(
      (a, b) =>
        laneOrder[a.item.lane] - laneOrder[b.item.lane] || rank(a.job, b.job),
    );
  const [selected, setSelected] = useState(text(rows[0]?.job.job.pipeline_id));
  const [stageKey, setStageKey] = useState("");
  const [lane, setLane] = useState<Lane | "all">("all");
  if (!rows.length)
    return (
      <p className="empty">
        {snapshot.sources.some(
          (source) =>
            source.name === "pipeline" && source.status === "complete",
        )
          ? "还没有岗位记录。"
          : "暂时无法读取岗位记录。"}
      </p>
    );
  const shown = rows.filter((row) => lane === "all" || row.item.lane === lane);
  const current =
    rows.find((row) => row.job.job.pipeline_id === selected) || rows[0];
  const unbound = all.filter(
    (stage) => !rows.some((row) => row.item.stages.includes(stage)),
  ).length;
  const chosen =
    current.item.stages.find((stage) => stage.key === stageKey) ||
    current.item.stages.at(-1);
  return (
    <section className="job-queue" aria-label="岗位进展">
      <div className="jq-summary" aria-label="按进展筛选">
        {laneNames.map(([key, name]) => (
          <button
            key={key}
            data-lane={key}
            aria-pressed={lane === key}
            onClick={() => setLane(lane === key ? "all" : key)}
          >
            {name}
            <strong>
              {rows.filter((row) => row.item.lane === key).length}
            </strong>
          </button>
        ))}
        {lane !== "all" && (
          <button className="jq-clear" onClick={() => setLane("all")}>
            显示全部
          </button>
        )}
      </div>
      <div className="jq-head" aria-hidden="true">
        <span>岗位</span>
        <span>我的进展</span>
        <span>需要你</span>
      </div>
      {shown.map(({ job, group, item }) => {
        const fit = group.ambiguous ? null : scoreOf(job);
        const decision = group.ambiguous ? "" : text(filterOf(job)?.decision);
        return (
          <div
            className="jq-row"
            data-job={text(job.job.job_id)}
            data-closed={closed(job)}
            data-lane={item.lane}
            key={text(job.job.pipeline_id)}
          >
            <div className="jq-job-info">
              <button
                className="jq-job"
                aria-pressed={current.job.job.pipeline_id === job.job.pipeline_id}
                title={text(job.job.title)}
                onClick={() => {
                  setSelected(text(job.job.pipeline_id));
                  setStageKey("");
                }}
              >
                {text(job.job.title)}
              </button>
              <div className="jq-company">
                <span>{text(job.job.company)}</span>
                {job.meta.paused === true && <span>已暂停</span>}
              </div>
              <div className="jq-rank">
                <span>基本要求：{filterNames[decision] || "未评估"}</span>
                <span>
                  匹配度：{fit === null ? "未评估" : Math.round(fit * 100)}
                </span>
              </div>
            </div>
            <div className="jq-progress">
              <p className="jq-milestone">
                {item.milestone}
                {item.milestoneAt != null && (
                  <time>{shortTime(item.milestoneAt)}</time>
                )}
              </p>
              <Progress item={item} />
            </div>
            <div className="jq-needs">
              {item.asks.length ? (
                item.asks.map((ask) => (
                  <p className="jq-ask" key={ask.text}>
                    <span>需要你</span>
                    {ask.text}
                  </p>
                ))
              ) : (
                <span className="jq-none">—</span>
              )}
            </div>
          </div>
        );
      })}
      {!shown.length && <p className="empty">没有符合这个筛选的岗位。</p>}
      {unbound > 0 && (
        <p className="jq-unbound">
          另有 {unbound} 项工作没有注明所属岗位，可在“运行记录”中查看。
        </p>
      )}
      <section className="jq-details" aria-live="polite">
        <div className="section-head">
          <h2>{text(current.job.job.title)}</h2>
          <span>
            {text(current.job.job.company)} / {text(current.job.job.platform)}
          </span>
        </div>
        <dl className="jq-report">
          <div>
            <dt>我做到了哪里</dt>
            <dd>
              {current.item.milestone}
              {unique(current.item.done).length > 0 &&
                `；已${unique(current.item.done).join("、")}`}
            </dd>
          </div>
          <div>
            <dt>我正在做</dt>
            <dd>
              {current.item.current.length
                ? current.item.current
                    .map((stage) => label(stage.event.activity))
                    .join("、")
                : current.item.unconfirmed.length
                  ? "有工作缺少近期更新，状态未确认"
                  : "当前没有进行中的工作"}
            </dd>
          </div>
          <div>
            <dt>我接下来准备</dt>
            <dd>
              {current.item.lane === "closed"
                ? "这个岗位已结束，不再推进"
                : current.item.next || "下一步尚未安排"}
            </dd>
          </div>
          <div>
            <dt>需要你</dt>
            <dd>
              {current.item.asks.length ? (
                <ul>
                  {current.item.asks.map((ask) => (
                    <li key={ask.text}>
                      <strong>{ask.text}</strong>
                      {ask.detail && <span>{ask.detail}</span>}
                    </li>
                  ))}
                </ul>
              ) : (
                "暂时不需要你处理"
              )}
            </dd>
          </div>
        </dl>
        {current.group.ambiguous && (
          <p role="status">
            这个岗位有多条尚未结束的联系记录，需要先核对，才能确定当前进展。
          </p>
        )}
        <h3>工作记录</h3>
        <div className="jq-phase-controls" aria-label="选择要查看的工作">
          {current.item.stages.map((stage) => (
            <button
              key={stage.key}
              aria-label={`${label(stage.event.activity)} / ${label(stage.status)} ${stage.started === null ? "开始未记录" : shortTime(stage.started)}，轮次 ${stage.runId}，阶段 ${stage.event.activity_id}`}
              title={`${stage.runId} / ${stage.event.activity_id}`}
              aria-pressed={chosen?.key === stage.key}
              data-status={stage.status}
              onClick={() => setStageKey(stage.key)}
            >
              {label(stage.event.activity)} / {label(stage.status)}{" "}
              {stage.started === null ? "开始未记录" : shortTime(stage.started)}
            </button>
          ))}
        </div>
        {chosen ? (
          <div className="jq-event-detail">
            <p>{text(chosen.event.message)}</p>
            <dl className="facts">
              <div>
                <dt>状态</dt>
                <dd>{label(chosen.status)}</dd>
              </div>
              <div>
                <dt>最近更新</dt>
                <dd>{shortTime(chosen.event.occurred_at)}</dd>
              </div>
              <div>
                <dt>执行者</dt>
                <dd>{chosen.event.owner}</dd>
              </div>
              <div>
                <dt>恢复点</dt>
                <dd>{text(chosen.event.checkpoint_reference)}</dd>
              </div>
            </dl>
            <button onClick={() => onTrace(chosen.runId)}>查看这次运行</button>
            <details>
              <summary>查看工作原始数据</summary>
              <pre>{JSON.stringify(chosen.event, null, 2)}</pre>
            </details>
          </div>
        ) : (
          <p className="note">还没有这个岗位的工作记录。</p>
        )}
        <details>
          <summary>查看岗位评估记录</summary>
          <pre>
            {JSON.stringify(
              {
                match_result: current.job.match_result ?? null,
                match_context: current.job.match_context ?? null,
                hard_filter_result: current.job.hard_filter_result ?? null,
                hard_filter_context: current.job.hard_filter_context ?? null,
              },
              null,
              2,
            )}
          </pre>
        </details>
        {!current.group.ambiguous && renderJobDetails(current.job)}
        <details>
          <summary>历次联系记录（{current.group.rounds.length}）</summary>
          <p className="note">每次联系的具体经过分别保存在下面。</p>
          {current.group.rounds.map((round) => (
            <pre key={text(round.job.pipeline_id)}>
              {JSON.stringify(round, null, 2)}
            </pre>
          ))}
        </details>
      </section>
    </section>
  );
}
