import { useState, type ReactNode } from "react";
import { channelOf, routedReport } from "./channels";
import { JobDialog } from "./JobDialog";
import { JobDetailTabs } from "./JobDetailTabs";
import { text, type JobView, type Snapshot } from "./contracts";
import {
  closed,
  contactGroups,
  label,
  report,
  scoreOf,
  shortTime,
  stages,
  type Lane,
  type Report,
  type Stage,
} from "./agentReport";
import { useHost } from "./hostContext";
import { personalTodos } from "./hostService";

const unique = (items: Stage[]) => [
  ...new Set(items.map((s) => label(s.event.activity))),
];
function Progress({ item }: { item: Report }) {
  const done = unique(item.done);
  return (
    <ol className="jq-flow" aria-label="工作进展">
      {!!done.length && <li className="done">已{done.slice(-3).join("、")}</li>}
      {item.failed.map((s) => (
        <li className="failed" key={s.key}>
          {label(s.event.activity)}失败
        </li>
      ))}
      {item.unconfirmed.map((s) => (
        <li className="unconfirmed" key={s.key}>
          {label(s.event.activity)}：状态未确认
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
function reasons(job: JobView): string {
  const match = job.match_result;
  if (!match) return "尚未读取匹配结论";
  const parts = [
    match.strengths,
    match.partial_matches,
    match.hard_gaps,
    match.uncertainties,
  ].flatMap((value) =>
    Array.isArray(value)
      ? value.map((item) =>
          typeof item === "string"
            ? item
            : item && typeof item === "object"
              ? String(item.message ?? item.reason ?? item.requirement ?? "")
              : "",
        )
      : [],
  );
  return parts.filter(Boolean).join("；") || "已保存匹配评估，具体理由尚未接入";
}
function stamp(value: unknown) {
  const n = typeof value === "string" ? Date.parse(value) : NaN;
  return Number.isFinite(n) ? n : -Infinity;
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
  const host = useHost();
  const todos = host ? personalTodos(host.state) : [];
  const all = stages(snapshot);
  const [sort, setSort] = useState("match");
  const rows = contactGroups(snapshot.jobs)
    .map((group) => {
      const job = group.representative;
      const ownTodos = todos.filter((t) =>
        group.rounds.some(
          (r) =>
            r.job.job_id === t.job_id && r.job.pipeline_id === t.contact_id,
        ),
      );
      const item = routedReport(
        job,
        report(
          job,
          group,
          all.filter(
            (s) =>
              channelOf(job).greetings || s.event.activity !== "draft_greeting",
          ),
        ),
      );
      // Explicit personal decisions only. Status reviews and missing host data do not create a red dot.
      item.asks = ownTodos.map((t) => ({
        text: t.question,
        detail: t.basis.join("；"),
      }));
      item.lane = closed(job)
        ? "closed"
        : ownTodos.length
          ? "needs"
          : item.current.length
            ? "active"
            : [
                  "greeting_sent",
                  "greeting_read",
                  "resume_sent",
                  "interviewed",
                ].includes(text(job.job.pipeline_state))
              ? "waiting"
              : "idle";
      const intake =
        host?.state.jobs.find((j) => j.contact_id === job.job.pipeline_id)
          ?.intake_at ?? job.job.created_at;
      return { group, job, item, intake };
    })
    .sort(
      (a, b) =>
        Number(closed(a.job)) - Number(closed(b.job)) ||
        (sort === "intake"
          ? stamp(b.intake) - stamp(a.intake)
          : (scoreOf(b.job) ?? -Infinity) - (scoreOf(a.job) ?? -Infinity)) ||
        0,
    );
  const [selected, setSelected] = useState("");
  const [opened, setOpened] = useState(false);
  const [initialTab, setInitialTab] = useState("progress");
  const [stageKey, setStageKey] = useState("");
  const [lane, setLane] = useState<Lane | "all">("all");
  const open = (job: JobView, tab = "progress") => {
    setSelected(text(job.job.pipeline_id));
    setStageKey("");
    setInitialTab(tab);
    setOpened(true);
  };
  if (!rows.length)
    return (
      <p className="empty">
        {snapshot.sources.some(
          (s) => s.name === "pipeline" && s.status === "complete",
        )
          ? "还没有岗位记录。"
          : "暂时无法读取岗位记录。"}
      </p>
    );
  const shown = rows.filter((r) => lane === "all" || r.item.lane === lane);
  const current =
    rows.find((r) => r.job.job.pipeline_id === selected) || rows[0];
  const chosen =
    current.item.stages.find((s) => s.key === stageKey) ||
    current.item.stages.at(-1);
  const unbound = all.filter(
    (s) => !rows.some((r) => r.item.stages.includes(s)),
  ).length;
  return (
    <section className="job-queue" aria-label="岗位进展">
      <div className="jq-summary" aria-label="按进展筛选">
        {(
          [
            ["all", "全部"],
            ["active", "正在推进"],
            ["needs", "需要你"],
            ["waiting", "等待对方"],
            ["closed", "已结束"],
          ] as const
        ).map(([key, name]) => (
          <button
            key={key}
            data-lane={key}
            aria-pressed={lane === key}
            onClick={() => setLane(lane === key ? "all" : key)}
          >
            {name}
            <strong>
              {rows.filter((r) => key === "all" || r.item.lane === key).length}
            </strong>
          </button>
        ))}
        {lane !== "all" && (
          <button className="jq-clear" onClick={() => setLane("all")}>
            显示全部
          </button>
        )}
        <label>
          排序{" "}
          <select
            aria-label="岗位排序"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="match">按匹配度</option>
            <option value="intake">按入库时间</option>
          </select>
        </label>
      </div>
      <div className="jq-head" aria-hidden="true">
        <span>岗位</span>
        <span>渠道</span>
        <span>匹配情况</span>
        <span>进展</span>
        <span>待处理</span>
      </div>
      {shown.map(({ job, group, item }) => (
        <div
          className="jq-row"
          data-job={text(job.job.job_id)}
          data-closed={closed(job)}
          data-lane={item.lane}
          key={text(job.job.pipeline_id)}
          tabIndex={0}
          aria-label={`查看 ${text(job.job.title)} 详情`}
          onKeyDown={(e) => {
            if (
              e.target === e.currentTarget &&
              ["Enter", " "].includes(e.key)
            ) {
              e.preventDefault();
              open(job);
            }
          }}
          onClick={(e) => {
            if (
              (e.target as HTMLElement).closest(
                "button,a,input,textarea,select,summary",
              ) ||
              window.getSelection()?.toString()
            )
              return;
            e.currentTarget.focus({ preventScroll: true });
            open(job);
          }}
        >
          <div className="jq-job-info">
            <button
              className="jq-job"
              title={text(job.job.title)}
              aria-pressed={current.job.job.pipeline_id === job.job.pipeline_id}
              onClick={() => open(job)}
            >
              {text(job.job.title)}
            </button>
            <div className="jq-company">
              <span>{text(job.job.company)}</span>
              {job.meta.paused === true && <span>已暂停</span>}
            </div>
            <strong className="jq-salary">{text(job.job.salary_raw)}</strong>
            <p>{text(job.job.location)}</p>
          </div>
          <div className="jq-channel-cell">
            <button
              className="jq-channel"
              aria-label={`${channelOf(job).name} 渠道详情`}
              onClick={() => open(job, "channel")}
            >
              {channelOf(job).name}
            </button>
          </div>
          <div className="jq-rank">
            <p>
              {group.ambiguous
                ? "存在多条未结束联系，评估适用范围需核对。"
                : reasons(job)}
            </p>
            {!group.ambiguous && scoreOf(job) !== null && (
              <small>已存匹配参考：{Math.round(scoreOf(job)! * 100)}%</small>
            )}
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
              <p className="jq-ask">
                <button
                  className="jq-attention"
                  onClick={() => open(job, "todo")}
                  aria-label={`需要你：${item.asks[0].text}`}
                >
                  <span className="host-dot" aria-hidden="true" />
                  需要你
                </button>
                {item.asks[0].text}
              </p>
            ) : (
              <span className="jq-none">
                {host?.source.mode === "snapshot" || !host
                  ? "待办来源未接入"
                  : "—"}
              </span>
            )}
          </div>
        </div>
      ))}
      {!shown.length && <p className="empty">没有符合这个筛选的岗位。</p>}
      {unbound > 0 && (
        <p className="jq-unbound">
          另有 {unbound} 项工作没有注明所属岗位，可在“运行记录”中查看。
        </p>
      )}
      {opened && (
        <JobDialog
          title={text(current.job.job.title)}
          onClose={() => setOpened(false)}
        >
          <div className="jq-details">
            <JobDetailTabs
              job={current.job}
              rounds={current.group.rounds}
              ambiguous={current.group.ambiguous}
              item={current.item}
              snapshot={snapshot}
              renderJobDetails={renderJobDetails}
              initialTab={initialTab}
              progress={
                <>
                  <dl className="jq-report">
                    <div>
                      <dt>我做到了哪里</dt>
                      <dd>{current.item.milestone}</dd>
                    </div>
                    <div>
                      <dt>我正在做</dt>
                      <dd>
                        {current.item.current.length
                          ? unique(current.item.current).join("、")
                          : current.item.unconfirmed.length
                            ? "工作缺少近期更新，状态未确认"
                            : "现有记录中没有进行中的工作"}
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
                        {current.item.asks.map((a) => a.text).join("；") ||
                          (host?.source.mode === "snapshot"
                            ? "待办来源未接入，尚无法确认"
                            : "本次核对范围内没有待决定事项")}
                      </dd>
                    </div>
                  </dl>
                  {current.group.ambiguous && (
                    <p>这个岗位有多条尚未结束的联系记录，当前进展待核对。</p>
                  )}
                  <h3>工作记录</h3>
                  <div
                    className="jq-phase-controls"
                    aria-label="选择要查看的工作"
                  >
                    {current.item.stages.map((stage) => (
                      <button
                        key={stage.key}
                        aria-label={`${label(stage.event.activity)} / ${label(stage.status)} ${stage.started === null ? "开始未记录" : shortTime(stage.started)}，轮次 ${stage.runId}，阶段 ${stage.event.activity_id}`}
                        aria-pressed={chosen?.key === stage.key}
                        data-status={stage.status}
                        onClick={() => setStageKey(stage.key)}
                      >
                        {label(stage.event.activity)} / {label(stage.status)}{" "}
                        {stage.started === null
                          ? "开始未记录"
                          : shortTime(stage.started)}
                      </button>
                    ))}
                  </div>
                  {chosen ? (
                    <div className="jq-event-detail">
                      <p>{text(chosen.event.message)}</p>
                      <p>
                        {label(chosen.status)} ·{" "}
                        {shortTime(chosen.event.occurred_at)}
                      </p>
                      <button onClick={() => onTrace(chosen.runId)}>
                        查看这次运行
                      </button>
                    </div>
                  ) : (
                    <p className="note">还没有这个岗位的工作记录。</p>
                  )}
                </>
              }
            />
          </div>
        </JobDialog>
      )}
    </section>
  );
}
