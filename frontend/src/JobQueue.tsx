import { useState, type ReactNode } from "react";
import {
  text,
  type Activity,
  type Fields,
  type JobView,
  type Snapshot,
} from "./contracts";

const names: Record<string, string> = {
  fetch: "采集",
  detail: "读取详情",
  match: "匹配",
  draft_greeting: "起草招呼",
  review: "复核",
  approval: "待审批",
  readback: "回读",
  report: "汇总",
  started: "执行中",
  heartbeat: "执行中",
  waiting: "等待处理",
  completed: "已完成",
  failed: "失败",
  unconfirmed: "状态未确认",
  draft_pending: "待准备 / 待发送",
  greeting_sent: "招呼已发",
  greeting_read: "招呼已读",
  initial_contact: "初步沟通",
  resume_requested: "索取简历",
  resume_sent: "简历已发",
  interview_pending: "待面试",
  interviewed: "已面试",
  abandoned: "放弃 / 关闭",
};
const label = (value: unknown) => names[text(value)] || text(value);
const wallclock = (value: number) =>
  new Date(value).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
const record = (value: unknown): Fields | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Fields)
    : null;
const match = (job: JobView) => record(job.match_result);
const filter = (job: JobView) => record(job.hard_filter_result);
const score = (job: JobView) =>
  typeof match(job)?.overall === "number"
    ? (match(job)!.overall as number)
    : null;
const closed = (job: JobView) => job.job.pipeline_state === "abandoned";
function compare(a: JobView, b: JobView) {
  if (closed(a) !== closed(b)) return Number(closed(a)) - Number(closed(b));
  const ranks: Record<string, number> = { pass: 0, review: 1, reject: 3 };
  const byFilter =
    (ranks[text(filter(a)?.decision)] ?? 2) -
    (ranks[text(filter(b)?.decision)] ?? 2);
  if (byFilter) return byFilter;
  return (score(b) ?? -Infinity) - (score(a) ?? -Infinity) || 0;
}
interface Stage {
  key: string;
  event: Activity;
  runId: string;
  start: number | null;
  end: number;
  status: string;
}
function stages(snapshot: Snapshot): Stage[] {
  return snapshot.runs.flatMap((run) =>
    Object.values(
      run.activities.reduce<Record<string, Activity[]>>((acc, event) => {
        (acc[event.activity_id] ??= []).push(event);
        return acc;
      }, {}),
    ).map((events) => {
      const event = events.at(-1)!;
      const began = events.find((e) => e.status === "started");
      const ended = events.findLast((e) =>
        ["completed", "failed"].includes(e.status),
      );
      return {
        key: `${text(run.run.run_id)}:${event.activity_id}`,
        event,
        runId: text(run.run.run_id),
        start: began ? Date.parse(began.occurred_at) : null,
        end: ended
          ? Date.parse(ended.occurred_at)
          : run.freshness === "current"
            ? Date.parse(snapshot.generated_at)
            : Date.parse(event.occurred_at),
        status:
          !ended && run.freshness !== "current" ? "unconfirmed" : event.status,
      };
    }),
  );
}
const belongs = (stage: Stage, job: JobView) =>
  typeof stage.event.job_id === "string" &&
  (stage.event.job_id === job.job.job_id ||
    stage.event.job_id === job.meta.normalized_job_id);
function contactGroups(items: JobView[]) {
  const groups: { aliases: Set<string>; rounds: JobView[] }[] = [];
  for (const job of items) {
    const aliases = new Set(
      [job.job.job_id, job.meta.normalized_job_id].filter(
        (id): id is string => typeof id === "string" && id.length > 0,
      ),
    );
    const linked = groups.filter((group) =>
      [...aliases].some((id) => group.aliases.has(id)),
    );
    const merged = { aliases, rounds: [job] };
    for (const group of linked) {
      for (const id of group.aliases) merged.aliases.add(id);
      merged.rounds.push(...group.rounds);
      groups.splice(groups.indexOf(group), 1);
    }
    groups.push(merged);
  }
  return groups.map(({ rounds }) => {
    const newest = [...rounds].sort(
      (a, b) =>
        Date.parse(text(b.job.entered_at)) -
          Date.parse(text(a.job.entered_at)) ||
        Number(b.meta.version) - Number(a.meta.version) ||
        text(b.job.pipeline_id).localeCompare(text(a.job.pipeline_id)),
    );
    const active = newest.filter((job) => !closed(job));
    return {
      rounds: newest,
      representative: active[0] || newest[0],
      ambiguous: active.length > 1,
    };
  });
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
  const groups = contactGroups(snapshot.jobs);
  const groupFor = (job: JobView) =>
    groups.find((group) => group.representative === job)!;
  const jobs = groups
    .map((group) => group.representative)
    .sort((a, b) => {
      if (closed(a) !== closed(b)) return Number(closed(a)) - Number(closed(b));
      if (groupFor(a).ambiguous !== groupFor(b).ambiguous)
        return Number(groupFor(a).ambiguous) - Number(groupFor(b).ambiguous);
      return compare(a, b);
    });
  const belongsJob = (stage: Stage, job: JobView) =>
    groupFor(job).rounds.some((round) => belongs(stage, round));
  const [selected, setSelected] = useState(text(jobs[0]?.job.pipeline_id));
  const [stageKey, setStageKey] = useState("");
  const [windowMode, setWindowMode] = useState<"recent" | "all">("recent");
  const all = stages(snapshot);
  const bound = all.filter((stage) =>
    jobs.some((job) => belongsJob(stage, job)),
  );
  const unbound = all.length - bound.length;
  const now = Date.parse(snapshot.generated_at);
  const earliest = Math.min(
    now - 60000,
    ...bound.map((stage) => stage.start ?? Date.parse(stage.event.occurred_at)),
  );
  const start = windowMode === "recent" ? now - 30 * 60000 : earliest;
  const range = Math.max(60000, now - start);
  const visible = (stage: Stage) =>
    (stage.start ?? Date.parse(stage.event.occurred_at)) <= now &&
    stage.end >= start;
  const outside = bound.filter((stage) => !visible(stage)).length;
  const current =
    jobs.find((job) => job.job.pipeline_id === selected) || jobs[0];
  const currentStages = current
    ? bound.filter((stage) => belongsJob(stage, current))
    : [];
  const currentStage =
    currentStages.find((stage) => stage.key === stageKey) ||
    currentStages.at(-1);
  if (!jobs.length)
    return (
      <p className="empty">
        {snapshot.sources.some(
          (source) =>
            source.name === "pipeline" && source.status === "complete",
        )
          ? "当前候选人尚无岗位记录。"
          : "岗位记录暂不可确认。"}
      </p>
    );
  return (
    <section className="job-queue" aria-label="岗位任务时间轴">
      <div className="section-head">
        <h2>岗位与执行进度</h2>
        <div className="jq-window">
          <button
            aria-pressed={windowMode === "recent"}
            onClick={() => setWindowMode("recent")}
          >
            近30分钟
          </button>
          <button
            aria-pressed={windowMode === "all"}
            onClick={() => setWindowMode("all")}
          >
            全部已记录
          </button>
        </div>
      </div>
      <p className="note">
        按已保存的硬筛结论与匹配值排序；放弃 / 关闭的岗位置后。
        {new Date(start).toLocaleDateString("zh-CN")} {wallclock(start)} 至{" "}
        {wallclock(now)}
      </p>
      <div className="jq-axis">
        <span>岗位 / 公司</span>
        <div className="jq-clock">
          {[0, 0.25, 0.5, 0.75, 1].map((fraction, index) => (
            <span key={fraction}>
              {index === 4
                ? `${wallclock(now)} 现在`
                : wallclock(start + range * fraction)}
            </span>
          ))}
        </div>
      </div>
      {jobs.map((job) => {
        const candidates = bound
          .filter((stage) => belongsJob(stage, job) && visible(stage))
          .sort((a, b) => (a.start ?? a.end) - (b.start ?? b.end));
        const laneEnds: number[] = [];
        const placed = candidates.map((stage) => {
          const from = Math.max(
            start,
            stage.start ?? Date.parse(stage.event.occurred_at),
          );
          const to = Math.min(now, stage.end);
          let lane = laneEnds.findIndex((end) => end <= from);
          if (lane < 0) lane = laneEnds.length;
          laneEnds[lane] = Math.max(from + 1, to);
          return {
            stage,
            lane,
            left: Math.max(0, ((from - start) / range) * 100),
            width: Math.max(0.35, ((Math.max(from, to) - from) / range) * 100),
          };
        });
        const decision = groupFor(job).ambiguous
          ? "unknown"
          : text(filter(job)?.decision);
        const fit = groupFor(job).ambiguous ? null : score(job);
        return (
          <div
            className="jq-row"
            data-job={text(job.job.job_id)}
            data-closed={closed(job)}
            key={text(job.job.pipeline_id)}
          >
            <div className="jq-job-info">
              <button
                className="jq-job"
                aria-pressed={current.job.pipeline_id === job.job.pipeline_id}
                title={text(job.job.title)}
                onClick={() => {
                  setSelected(text(job.job.pipeline_id));
                  setStageKey("");
                }}
              >
                {text(job.job.title)}
              </button>
              <div className="jq-company">{text(job.job.company)}</div>
              <div className="jq-rank">
                {job.meta.paused === true && <span>已暂停</span>}
                <span>
                  {groupFor(job).ambiguous
                    ? "联系轮次冲突，待核验"
                    : label(job.job.pipeline_state)}
                </span>
                <span>
                  硬筛：
                  {(
                    {
                      pass: "通过",
                      review: "待复核",
                      reject: "不通过",
                    } as Record<string, string>
                  )[decision] || "未评估"}
                </span>
                <span>
                  匹配：
                  {fit === null ? "未评估" : `${Math.round(fit * 100)} / 100`}
                </span>
              </div>
            </div>
            <div className="jq-track-group">
              <div
                className="jq-lanes"
                style={{ minHeight: `${Math.max(1, laneEnds.length) * 40}px` }}
                aria-label={`${text(job.job.title)}的已关联阶段`}
                role="img"
              >
                {placed.map(({ stage, lane, left, width }) => (
                  <div
                    className={`jq-mark ${stage.status}`}
                    key={stage.key}
                    data-start={stage.start}
                    data-activity={stage.event.activity_id}
                    data-status={stage.status}
                    style={{
                      left: `${Math.min(99.65, left)}%`,
                      width: `${Math.min(width, 100 - left)}%`,
                      top: `${lane * 40}px`,
                    }}
                    title={`${label(stage.event.activity)}，${label(stage.status)}，${stage.start === null ? "开始时间未记录" : wallclock(stage.start)}`}
                  >
                    <span className="jq-mark-label">
                      {width >= 10 ? label(stage.event.activity) : ""}
                    </span>
                  </div>
                ))}
                {!placed.length && (
                  <span className="track-empty">
                    {candidates.length
                      ? "当前窗口无阶段"
                      : "当前窗口无已关联阶段"}
                  </span>
                )}
              </div>
              {placed.length > 0 && (
                <div className="jq-stage-key" aria-label="当前窗口已记录阶段">
                  {Object.entries(
                    placed.reduce<Record<string, number>>((acc, { stage }) => {
                      acc[stage.event.activity] =
                        (acc[stage.event.activity] || 0) + 1;
                      return acc;
                    }, {}),
                  ).map(([activity, count]) => (
                    <span key={activity}>
                      {label(activity)}
                      {count > 1 ? ` × ${count}` : ""}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
      {outside > 0 && (
        <p className="note">
          当前时间窗口外还有 {outside}{" "}
          个已关联阶段；选择“全部已记录”查看，详情保留完整事件。
        </p>
      )}
      <p className="jq-unbound">
        未绑定岗位的阶段：{unbound} 个。保留在轮次追溯中，不推测所属岗位。
      </p>
      <section className="jq-details" aria-live="polite">
        <div className="section-head">
          <h2>{text(current.job.title)}</h2>
          <span>{text(current.job.company)}</span>
        </div>
        <div className="jq-phase-controls" aria-label="本岗阶段选择">
          {currentStages.map((stage) => (
            <button
              key={stage.key}
              aria-label={`${label(stage.event.activity)} / ${label(stage.status)} ${stage.start === null ? "开始未记录" : wallclock(stage.start)}，轮次 ${stage.runId}，阶段 ${stage.event.activity_id}`}
              title={`${stage.runId} / ${stage.event.activity_id}`}
              aria-pressed={currentStage?.key === stage.key}
              onClick={() => setStageKey(stage.key)}
            >
              {label(stage.event.activity)} / {label(stage.status)}{" "}
              {stage.start === null ? "开始未记录" : wallclock(stage.start)}
            </button>
          ))}
        </div>
        {currentStage ? (
          <div className="jq-event-detail">
            <h3>{label(currentStage.event.activity)}</h3>
            <p>{text(currentStage.event.message)}</p>
            <dl className="facts">
              <div>
                <dt>阶段状态</dt>
                <dd>{label(currentStage.status)}</dd>
              </div>
              <div>
                <dt>开始时间</dt>
                <dd>
                  {currentStage.start === null
                    ? "未记录"
                    : new Date(currentStage.start).toLocaleString("zh-CN")}
                </dd>
              </div>
              <div>
                <dt>最近事件</dt>
                <dd>
                  {new Date(currentStage.event.occurred_at).toLocaleString(
                    "zh-CN",
                  )}
                </dd>
              </div>
              <div>
                <dt>接下来由谁处理</dt>
                <dd>{currentStage.event.owner}</dd>
              </div>
            </dl>
            <p>恢复点：{text(currentStage.event.checkpoint_reference)}</p>
            <button onClick={() => onTrace(currentStage.runId)}>
              查看所属轮次
            </button>
            <details>
              <summary>完整阶段字段</summary>
              <pre>{JSON.stringify(currentStage.event, null, 2)}</pre>
            </details>
          </div>
        ) : (
          <p>尚无明确绑定本岗位的阶段记录。</p>
        )}
        <details>
          <summary>匹配与硬筛原始记录</summary>
          <pre>
            {JSON.stringify(
              {
                match_result: current.match_result ?? null,
                match_context: current.match_context ?? null,
                hard_filter_result: current.hard_filter_result ?? null,
                hard_filter_context: current.hard_filter_context ?? null,
              },
              null,
              2,
            )}
          </pre>
        </details>
        {groupFor(current).ambiguous ? (
          <p role="status">
            存在多个未关闭联系轮次，当前岗位状态暂不可确认，请核验原始记录。
          </p>
        ) : (
          renderJobDetails(current)
        )}
        <details>
          <summary>全部联系轮次（{groupFor(current).rounds.length}）</summary>
          <p>
            各联系轮次独立保留；上方阶段按明确的岗位编号跨轮次展示，不合并业务历史。
          </p>
          {groupFor(current).rounds.map((round) => (
            <pre key={text(round.job.pipeline_id)}>
              {JSON.stringify(round, null, 2)}
            </pre>
          ))}
        </details>
      </section>
    </section>
  );
}
