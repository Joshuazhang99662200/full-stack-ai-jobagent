import { useState } from "react";
import { JobQueue } from "./JobQueue";
import { channelOf } from "./channels";
import type {
  Activity,
  Definitions,
  Fields,
  JobView,
  RunView,
  Snapshot,
} from "./contracts";
import { text } from "./contracts";
import "./styles.css";
import { HostContext, type HostController } from "./hostContext";
import { HostControls } from "./HostControls";
export { SourceConsole } from "./SourceConsole";
export {
  createSnapshotSource,
  createHttpSource,
  type ConsoleDataSource,
} from "./dataSource";
export { createDemoSource, type DemoStorage } from "./demoHost";
export type { HostState } from "./hostContracts";
export type { Snapshot, Definitions } from "./contracts";
export interface ConsoleProps {
  snapshot: Snapshot;
  definitions?: Definitions;
  demo?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
  initialView?: string;
  syncUrl?: boolean;
  onViewChange?: (view: string) => void;
  host?: HostController;
}
const labels: Record<string, string> = {
  draft_pending: "待准备 / 待发送",
  greeting_sent: "招呼已发",
  greeting_read: "招呼已读",
  initial_contact: "初步沟通",
  resume_requested: "对方索要简历",
  resume_sent: "简历已发",
  interview_pending: "待面试",
  interviewed: "已面试",
  abandoned: "放弃 / 关闭",
  fetch: "获取信息",
  detail: "查看详情",
  match: "评估匹配度",
  draft_greeting: "写招呼语",
  review: "检查材料",
  approval: "待审批",
  readback: "核对结果",
  report: "整理结果",
  running: "执行中",
  waiting_for_approval: "等待审批",
  waiting_for_login: "等待登录",
  waiting_for_fact_confirmation: "待你确认信息",
  waiting_for_job_selection: "待你选择岗位",
  waiting_for_review: "等待检查材料",
  delivery_outcome_unknown: "投递结果未知",
  completed: "已结束",
  failed: "失败",
  cancelled: "已取消",
  new: "未开始",
  started: "执行中",
  heartbeat: "执行中",
  waiting: "等待处理",
  stale: "状态未确认",
  unknown: "状态未确认",
};
const stateNames = [
  "draft_pending",
  "greeting_sent",
  "greeting_read",
  "initial_contact",
  "resume_requested",
  "resume_sent",
  "interview_pending",
  "interviewed",
  "abandoned",
];
const label = (value: unknown) => labels[text(value)] || text(value);
const when = (value: unknown) =>
  typeof value === "string"
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "时间未记录";
const params = () =>
  typeof window === "undefined"
    ? new URLSearchParams()
    : new URLSearchParams(window.location.search);
const remember = (key: string, value: string) => {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set(key, value);
  window.history.replaceState(null, "", url);
};
const noop = (_key: string, _value: string) => {};
function FieldsView({ value }: { value: Fields }) {
  return (
    <dl className="fields">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{text(item)}</dd>
        </div>
      ))}
    </dl>
  );
}
function ActivityDetail({
  event,
  stale = false,
}: {
  event: Activity;
  stale?: boolean;
}) {
  return (
    <section className="detail" aria-live="polite">
      <h3>{label(event.activity)}</h3>
      <p>{text(event.message)}</p>
      <dl className="facts">
        <div>
          <dt>最近更新</dt>
          <dd>{when(event.occurred_at)}</dd>
        </div>
        <div>
          <dt>当前状态</dt>
          <dd>
            {stale && !["completed", "failed"].includes(event.status)
              ? "状态未确认"
              : label(event.status)}
          </dd>
        </div>
        <div>
          <dt>接下来由谁处理</dt>
          <dd>{event.owner}</dd>
        </div>
        <div>
          <dt>继续任务时参考</dt>
          <dd>{text(event.checkpoint_reference)}</dd>
        </div>
      </dl>
      <p className="note">
        这里显示助手记录的工作过程；是否已批准或发送，请查看对应记录。
      </p>
      <details>
        <summary>查看任务原始数据</summary>
        <FieldsView value={event} />
      </details>
    </section>
  );
}
function RunPanel({
  items,
  now,
  write,
  syncUrl,
  emptyConfirmed,
}: {
  emptyConfirmed: boolean;
  items: RunView[];
  now: string;
  write: typeof noop;
  syncUrl: boolean;
}) {
  const saved = syncUrl ? params().get("run") : null;
  const [selected, setSelected] = useState(saved || text(items[0]?.run.run_id));
  const [eventId, setEventId] = useState("");
  if (!items.length)
    return (
      <p className="empty">
        {emptyConfirmed ? "还没有运行记录。" : "暂时无法读取运行记录。"}
      </p>
    );
  const current =
    items.find((item) => item.run.run_id === selected) || items[0];
  const events = current.activities;
  const chosen =
    events.find((event) => event.event_id === eventId) || events.at(-1);
  const extent = Math.max(
    1,
    ...items.map((item) => {
      const start = Date.parse(text(item.run.created_at));
      const latest = item.activities.at(-1);
      const end =
        item.freshness === "current"
          ? Date.parse(now)
          : Date.parse(latest?.occurred_at || text(item.run.updated_at));
      return Math.max(0, (end - start) / 60000) || 1;
    }),
  );
  return (
    <>
      <div className="section-head">
        <h2>每次运行做了什么</h2>
        <span>从各次运行开始计时，单位：分钟</span>
      </div>
      <div className="timeline" aria-label="轮次活动时间轴">
        <div className="axis">
          <span>运行记录 / 状态</span>
          <div>
            {[0, 0.25, 0.5, 0.75, 1].map((n) => (
              <span key={n}>{Math.round(extent * n)}</span>
            ))}
          </div>
        </div>
        {items.map((item, index) => {
          const start = Date.parse(text(item.run.created_at));
          const grouped = Object.values(
            item.activities.reduce<Record<string, Activity[]>>((acc, e) => {
              (acc[e.activity_id] ??= []).push(e);
              return acc;
            }, {}),
          );
          return (
            <div
              className={`lane ${current.run.run_id === item.run.run_id ? "selected" : ""}`}
              key={text(item.run.run_id)}
            >
              <div className="run-meta">
                <button
                  className="run-pick"
                  aria-pressed={current.run.run_id === item.run.run_id}
                  onClick={() => {
                    setSelected(text(item.run.run_id));
                    setEventId("");
                    write("run", text(item.run.run_id));
                  }}
                >
                  <strong>{text(item.run.run_id).slice(0, 12)}</strong>
                </button>
                <div className="run-facts">
                  <span>{label(item.run.phase)}</span>
                  {(item.freshness === "stale" ||
                    item.freshness === "unknown") && (
                    <span>阶段状态未确认</span>
                  )}
                  <small>{when(item.run.created_at)}</small>
                </div>
              </div>
              <div
                className="track"
                role="img"
                aria-label={
                  grouped
                    .map((group) => {
                      const event = group.at(-1)!;
                      return `${label(event.activity)}：${item.freshness !== "current" && !["completed", "failed"].includes(event.status) ? "状态未确认" : label(event.status)}`;
                    })
                    .join("；") || "阶段时间未记录"
                }
              >
                {grouped.map((group) => {
                  const latest = group.at(-1)!;
                  const begin = group.find((e) => e.status === "started");
                  const finish = group.findLast((e) =>
                    ["completed", "failed"].includes(e.status),
                  );
                  const point = Date.parse(
                    begin?.occurred_at || latest.occurred_at,
                  );
                  const end = finish
                    ? Date.parse(finish.occurred_at)
                    : item.freshness === "current"
                      ? Date.parse(now)
                      : Date.parse(latest.occurred_at);
                  const left = Math.max(
                    0,
                    Math.min(98, ((point - start) / 60000 / extent) * 100),
                  );
                  const width = begin
                    ? Math.max(
                        1,
                        Math.min(
                          100 - left,
                          ((end - point) / 60000 / extent) * 100,
                        ),
                      )
                    : 1;
                  return (
                    <span
                      aria-hidden="true"
                      key={latest.activity_id}
                      className={`span ${item.freshness !== "current" && !finish ? "stale" : latest.status} ${!begin ? "point" : ""}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                    />
                  );
                })}
                {!grouped.length && (
                  <span className="track-empty">还没有记录各步骤的时间</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="legend">
        <span>淡蓝：正在进行</span>
        <span>浅灰：已完成</span>
        <span>浅黄：等待处理</span>
        <span>短线：缺少开始时间</span>
      </div>
      <div className="phase-picks" aria-label="本轮阶段选择">
        {Object.values(
          events.reduce<Record<string, Activity>>((acc, event) => {
            acc[event.activity_id] = event;
            return acc;
          }, {}),
        ).map((event) => (
          <button
            key={event.activity_id}
            aria-pressed={chosen?.activity_id === event.activity_id}
            onClick={() => setEventId(event.event_id)}
          >
            {label(event.activity)}
          </button>
        ))}
      </div>
      <section className="selection">
        <div className="section-head">
          <h2>本次运行详情</h2>
          <span>{label(current.run.phase)}</span>
        </div>
        {current.freshness !== "current" &&
          current.freshness !== "terminal" && (
            <p role="status" className="notice">
              缺少近期更新，暂时无法确认任务是否仍在进行。
            </p>
          )}
        {chosen ? (
          <ActivityDetail
            event={chosen}
            stale={current.freshness !== "current"}
          />
        ) : (
          <p>还没有具体步骤的记录，暂时无法显示任务进度。</p>
        )}
        <details>
          <summary>查看本次运行的原始数据</summary>
          <FieldsView value={current.run} />
        </details>
      </section>
    </>
  );
}
function JobPanel({
  items,
  write,
  syncUrl,
  emptyConfirmed,
  embedded = false,
}: {
  emptyConfirmed: boolean;
  embedded?: boolean;
  items: JobView[];
  write: typeof noop;
  syncUrl: boolean;
}) {
  const orderedItems = [...items].sort(
    (a, b) =>
      Number(a.job.pipeline_state === "abandoned") -
      Number(b.job.pipeline_state === "abandoned"),
  );
  const saved = syncUrl ? params().get("job") : null;
  const [selected, setSelected] = useState(
    saved || text(orderedItems[0]?.job.pipeline_id),
  );
  if (!items.length)
    return (
      <p className="empty">
        {emptyConfirmed ? "还没有岗位记录。" : "暂时无法读取岗位记录。"}
      </p>
    );
  const item =
    orderedItems.find((entry) => entry.job.pipeline_id === selected) ||
    orderedItems[0];
  const visited = new Set(item.history.map((event) => text(event.to_state)));
  return (
    <>
      {!embedded && (
        <>
          <div className="section-head">
            <h2>与招聘方的沟通进展</h2>
            <span>
              {channelOf(item).greetings
                ? "查看已发招呼、简历和面试等进展"
                : "查看简历、投递和面试等进展"}
            </span>
          </div>
          <div className="job-list">
            {orderedItems.map((entry, index) => (
              <button
                key={text(entry.job.pipeline_id)}
                aria-pressed={item.job.pipeline_id === entry.job.pipeline_id}
                onClick={() => {
                  setSelected(text(entry.job.pipeline_id));
                  write("job", text(entry.job.pipeline_id));
                }}
              >
                <strong>{text(entry.job.title)}</strong>
                <span>
                  {text(entry.job.company)} / {text(entry.job.platform)}
                </span>
                <span>{label(entry.job.pipeline_state)}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <section className="selection">
        {!embedded && <h2>{text(item.job.title)}</h2>}
        <div className="states" aria-label="沟通进展">
          {stateNames
            .filter(
              (state) =>
                channelOf(item).greetings || !state.startsWith("greeting_"),
            )
            .map((state) => (
              <div
                key={state}
                data-state={state}
                data-visited={visited.has(state)}
                aria-current={
                  item.job.pipeline_state === state ? "step" : undefined
                }
              >
                <span>
                  {item.job.pipeline_state === state
                    ? "当前"
                    : visited.has(state)
                      ? "已记录"
                      : "未记录"}
                </span>
                <strong>{label(state)}</strong>
              </div>
            ))}
        </div>
        <h3>进展记录</h3>
        <ol className="history">
          {item.history.map((entry, index) => (
            <li key={text(entry.history_id) || index}>
              <time>{when(entry.changed_at)}</time>
              <strong>
                {!channelOf(item).greetings &&
                text(entry.to_state).startsWith("greeting_")
                  ? "历史状态待核对"
                  : label(entry.to_state)}
              </strong>
              <span>
                {typeof entry.reason === "string"
                  ? entry.reason
                  : "已保存进展记录；核验依据可在排查信息中查看。"}
              </span>
            </li>
          ))}
        </ol>
        <details>
          <summary>查看岗位原始数据</summary>
          <h3>岗位信息</h3>
          <FieldsView value={item.job} />
          <h3>来源与版本</h3>
          <FieldsView value={item.meta} />
          <h3>进展原始记录</h3>
          <pre>{JSON.stringify(item.history, null, 2)}</pre>
        </details>
      </section>
    </>
  );
}
export function Console({
  snapshot,
  definitions = {},
  demo = false,
  onRefresh,
  refreshing = false,
  initialView,
  syncUrl = false,
  onViewChange,
  host,
}: ConsoleProps) {
  const [view, setView] = useState(
    initialView || (syncUrl ? params().get("view") : null) || "queue",
  );
  const write = syncUrl ? remember : noop;
  const [more, setMore] = useState(false);
  const pick = (value: string) => {
    setView(value);
    write("view", value);
    onViewChange?.(value);
  };
  return (
    <HostContext.Provider value={host ?? null}>
      <main className="ja-console">
        <header className="masthead">
          <div>
            <h1>岗位进展</h1>
            <p>查看每个岗位正在做什么，以及哪些事项需要你处理。</p>
          </div>
          <div className="header-actions">
            <button aria-expanded={more} onClick={() => setMore(!more)}>
              更多
            </button>
            {more && (
              <button
                onClick={() => {
                  pick("fields");
                  setMore(false);
                }}
              >
                排查问题
              </button>
            )}
            {demo && <span className="demo">合成示例</span>}
            {onRefresh && (
              <button
                className="refresh"
                onClick={onRefresh}
                disabled={refreshing}
              >
                {refreshing ? "刷新中" : "刷新"}
              </button>
            )}
          </div>
        </header>
        <div className="context">
          <span>本页读取于 {when(snapshot.generated_at)}</span>
          <span>
            {host?.source.mode === "demo"
              ? "合成交互演示"
              : host?.source.mode === "host"
                ? "宿主已接入"
                : "仅供查看"}
          </span>
        </div>
        <HostControls />
        <nav role="tablist" aria-label="控制台视图">
          {[
            ["queue", "任务进度"],
            ["runs", "运行记录"],
            ["jobs", "沟通进展"],
          ].map(([key, name]) => (
            <button
              key={key}
              id={`tab-${key}`}
              role="tab"
              aria-controls="console-panel"
              aria-selected={view === key}
              onClick={() => pick(key)}
            >
              {name}
            </button>
          ))}
        </nav>
        <div role="tabpanel" id="console-panel" aria-labelledby={`tab-${view}`}>
          {view === "queue" ? (
            <JobQueue
              snapshot={snapshot}
              onTrace={(runId) => {
                write("run", runId);
                pick("runs");
              }}
              renderJobDetails={(job) => (
                <JobPanel
                  items={[job]}
                  embedded
                  write={write}
                  syncUrl={syncUrl}
                  emptyConfirmed={true}
                />
              )}
            />
          ) : view === "runs" ? (
            <RunPanel
              items={snapshot.runs}
              now={snapshot.generated_at}
              write={write}
              syncUrl={syncUrl}
              emptyConfirmed={snapshot.sources.some(
                (source) =>
                  source.name === "harness" && source.status === "complete",
              )}
            />
          ) : view === "jobs" ? (
            <JobPanel
              items={snapshot.jobs}
              write={write}
              syncUrl={syncUrl}
              emptyConfirmed={snapshot.sources.some(
                (source) =>
                  source.name === "pipeline" && source.status === "complete",
              )}
            />
          ) : (
            <section className="contracts">
              <h2>接入时可用的数据</h2>
              <p>
                供接入工具或排查问题时查看。下面列出可读取的数据项、格式和可选值；没有记录的内容保持为空。
              </p>
              <pre>{JSON.stringify(definitions, null, 2)}</pre>
              {host && (
                <details>
                  <summary>宿主操作与保存结果</summary>
                  <pre>{JSON.stringify(host.state, null, 2)}</pre>
                </details>
              )}
              <details>
                <summary>查看本页完整数据（JSON）</summary>
                <pre>{JSON.stringify(snapshot, null, 2)}</pre>
              </details>
            </section>
          )}
        </div>
        <footer>
          <details>
            <summary>查看来源读取情况</summary>
            <ul className="sources">
              {snapshot.sources.map((source) => (
                <li key={source.name}>
                  <strong>{source.name}</strong>
                  <span>
                    {(
                      {
                        complete: "已读取",
                        missing: "未找到数据",
                        invalid: "数据无法读取",
                        unsupported: "暂未接入",
                      } as Record<string, string>
                    )[source.status] || source.status}
                  </span>
                  {source.message && <span>{source.message}</span>}
                </li>
              ))}
            </ul>
          </details>
          <p>发送招呼语或简历前，仍需你逐项确认。</p>
        </footer>
      </main>
    </HostContext.Provider>
  );
}
