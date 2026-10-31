import { useState } from "react";
import { JobQueue } from "./JobQueue";
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
}
const labels: Record<string, string> = {
  draft_pending: "待准备 / 待发送",
  greeting_sent: "招呼已发",
  greeting_read: "招呼已读",
  initial_contact: "初步沟通",
  resume_requested: "索取简历",
  resume_sent: "简历已发",
  interview_pending: "待面试",
  interviewed: "已面试",
  abandoned: "放弃 / 关闭",
  fetch: "采集",
  detail: "读取详情",
  match: "匹配",
  draft_greeting: "起草招呼",
  review: "复核",
  approval: "待审批",
  readback: "回读",
  report: "汇总",
  running: "执行中",
  waiting_for_approval: "等待审批",
  waiting_for_login: "等待登录",
  waiting_for_fact_confirmation: "等待事实确认",
  waiting_for_job_selection: "等待岗位选择",
  waiting_for_review: "等待复核",
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
          <dt>最近事件</dt>
          <dd>{when(event.occurred_at)}</dd>
        </div>
        <div>
          <dt>事件状态</dt>
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
          <dt>恢复点</dt>
          <dd>{text(event.checkpoint_reference)}</dd>
        </div>
      </dl>
      <p className="note">宿主活动上报，不代表审批或发送事实。</p>
      <details>
        <summary>完整活动字段</summary>
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
        {emptyConfirmed ? "当前候选人尚无运行记录。" : "运行记录暂不可确认。"}
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
        <h2>运行轨迹</h2>
        <span>各轮开始后的分钟数</span>
      </div>
      <div className="timeline" aria-label="轮次活动时间轴">
        <div className="axis">
          <span>轮次 / 运行状态</span>
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
                  <span className="track-empty">阶段时间未记录</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="legend">
        <span>淡蓝：当前阶段</span>
        <span>浅灰：已完成</span>
        <span>琥珀：等待处理</span>
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
          <h2>本轮详情</h2>
          <span>{label(current.run.phase)}</span>
        </div>
        {current.freshness !== "current" &&
          current.freshness !== "terminal" && (
            <p role="status" className="notice">
              状态未确认：最近心跳已过期，请先核验。
            </p>
          )}
        {chosen ? (
          <ActivityDetail
            event={chosen}
            stale={current.freshness !== "current"}
          />
        ) : (
          <p>尚无活动事件；不推断内部阶段。</p>
        )}
        <details>
          <summary>完整运行字段</summary>
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
        {emptyConfirmed ? "当前候选人尚无岗位记录。" : "岗位记录暂不可确认。"}
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
            <h2>岗位业务进度</h2>
            <span>审批材料与九态分别记录</span>
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
        <div className="states" aria-label="岗位九态">
          {stateNames.map((state) => (
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
        <h3>实际状态转移</h3>
        <ol className="history">
          {item.history.map((entry, index) => (
            <li key={text(entry.history_id) || index}>
              <time>{when(entry.changed_at)}</time>
              <strong>{label(entry.to_state)}</strong>
              <span>{text(entry.evidence_reference)}</span>
            </li>
          ))}
        </ol>
        <details>
          <summary>完整业务字段</summary>
          <h3>岗位字段</h3>
          <FieldsView value={item.job} />
          <h3>元数据</h3>
          <FieldsView value={item.meta} />
          <h3>原始转移记录</h3>
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
}: ConsoleProps) {
  const [view, setView] = useState(
    initialView || (syncUrl ? params().get("view") : null) || "queue",
  );
  const write = syncUrl ? remember : noop;
  const pick = (value: string) => {
    setView(value);
    write("view", value);
    onViewChange?.(value);
  };
  return (
    <main className="ja-console">
      <header className="masthead">
        <div>
          <h1>岗位任务队列</h1>
          <p>按岗位查看并行阶段、等待处理与业务进度。</p>
        </div>
        <div className="header-actions">
          {demo && <span className="demo">合成示例</span>}
          {onRefresh && (
            <button
              className="refresh"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? "读取中" : "刷新记录"}
            </button>
          )}
        </div>
      </header>
      <div className="context">
        <span>候选人 {snapshot.candidate_id}</span>
        <span>快照 {when(snapshot.generated_at)}</span>
        <span>只读视图</span>
      </div>
      <nav role="tablist" aria-label="控制台视图">
        {[
          ["queue", "岗位任务"],
          ["runs", "轮次追溯"],
          ["jobs", "岗位九态"],
          ["fields", "字段契约"],
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
            <h2>宿主可读取的完整契约</h2>
            <p>
              业务字段来自 Python
              权威模型，空值保留；定义包含类型、枚举和引用关系。
            </p>
            <pre>{JSON.stringify(definitions, null, 2)}</pre>
            <details>
              <summary>完整当前快照 JSON</summary>
              <pre>{JSON.stringify(snapshot, null, 2)}</pre>
            </details>
          </section>
        )}
      </div>
      <footer>
        <h2>数据来源</h2>
        <ul className="sources">
          {snapshot.sources.map((source) => (
            <li key={source.name}>
              <strong>{source.name}</strong>
              <span>
                {(
                  {
                    complete: "完整读取",
                    missing: "来源缺失",
                    invalid: "来源无效",
                    unsupported: "尚未支持",
                  } as Record<string, string>
                )[source.status] || source.status}
              </span>
              {source.message && <span>{source.message}</span>}
            </li>
          ))}
        </ul>
        <p>缺失时间不补造。审批与发送仍通过原有逐项门禁完成。</p>
      </footer>
    </main>
  );
}
