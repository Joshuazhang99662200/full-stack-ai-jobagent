/** Per-job agent report derived only from recorded activities and pipeline facts. */
import {
  text,
  type Activity,
  type Fields,
  type JobView,
  type Snapshot,
} from "./contracts";

export const names: Record<string, string> = {
  fetch: "获取信息",
  detail: "查看详情",
  match: "评估匹配度",
  draft_greeting: "写招呼语",
  review: "检查材料",
  approval: "准备审批",
  readback: "核对结果",
  report: "整理结果",
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
  resume_requested: "对方索要简历",
  resume_sent: "简历已发",
  interview_pending: "待面试",
  interviewed: "已面试",
  abandoned: "放弃 / 关闭",
  employer_rejected: "对方婉拒",
  job_closed: "岗位已关闭",
  user_abandoned: "本人放弃",
  read_no_reply_2d: "已读未回",
  no_reply_2d: "未回复",
};
export const label = (value: unknown) => names[text(value)] || text(value);
export const shortTime = (value: unknown) =>
  typeof value === "string"
    ? new Date(value).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "时间未记录";

/** What the job's business state means, phrased as the agent reporting it. */
const milestones: Record<string, string> = {
  draft_pending: "还没有联系招聘方",
  greeting_sent: "招呼已发，等对方查看",
  greeting_read: "对方已读招呼，等对方回复",
  initial_contact: "已和对方初步沟通",
  resume_requested: "对方索要简历",
  resume_sent: "简历已发，等对方反馈",
  interview_pending: "待面试",
  interviewed: "已面试，等对方结果",
  abandoned: "已放弃 / 关闭",
};
const waitingForOther = new Set([
  "greeting_sent",
  "greeting_read",
  "resume_sent",
  "interviewed",
]);

/** Explicit host waits only; a run's phase is never spread onto unrelated jobs. */
const asksByPhase: Record<string, string> = {
  waiting_for_approval: "审阅准确正文与附件，逐项批准",
  waiting_for_login: "在平台上重新登录",
  waiting_for_fact_confirmation: "确认相关经历事实",
  waiting_for_job_selection: "选择要推进的岗位",
  waiting_for_review: "检查准备好的材料",
  delivery_outcome_unknown: "核对投递是否真的成功",
};
const asksByActivity: Record<string, string> = {
  approval: "审阅准确正文与附件，逐项批准",
  review: "检查准备好的材料",
};

export interface Stage {
  key: string;
  event: Activity;
  runId: string;
  runPhase: string;
  started: string | null;
  status: string;
}
export function stages(snapshot: Snapshot): Stage[] {
  return snapshot.runs.flatMap((run) =>
    Object.values(
      run.activities.reduce<Record<string, Activity[]>>((acc, event) => {
        (acc[event.activity_id] ??= []).push(event);
        return acc;
      }, {}),
    ).map((events) => {
      const event = events.at(-1)!;
      const ended = ["completed", "failed"].includes(event.status);
      return {
        key: `${text(run.run.run_id)}:${event.activity_id}`,
        event,
        runId: text(run.run.run_id),
        runPhase: text(run.run.phase),
        started:
          events.find((e) => e.status === "started")?.occurred_at ?? null,
        status:
          !ended && run.freshness !== "current" ? "unconfirmed" : event.status,
      };
    }),
  );
}
const at = (stage: Stage) =>
  Date.parse(stage.started ?? stage.event.occurred_at);

const record = (value: unknown): Fields | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Fields)
    : null;
export const filterOf = (job: JobView) => record(job.hard_filter_result);
export const scoreOf = (job: JobView) => {
  const overall = record(job.match_result)?.overall;
  return typeof overall === "number" ? overall : null;
};
export const closed = (job: JobView) => job.job.pipeline_state === "abandoned";
export const belongs = (stage: Stage, job: JobView) =>
  typeof stage.event.job_id === "string" &&
  (stage.event.job_id === job.job.job_id ||
    stage.event.job_id === job.meta.normalized_job_id);

export interface ContactGroup {
  rounds: JobView[];
  representative: JobView;
  ambiguous: boolean;
}
export function contactGroups(items: JobView[]): ContactGroup[] {
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

export interface Ask {
  text: string;
  detail: string | null;
}
export type Lane = "needs" | "active" | "waiting" | "idle" | "closed";
export interface Report {
  lane: Lane;
  milestone: string;
  milestoneAt: unknown;
  done: Stage[];
  current: Stage[];
  unconfirmed: Stage[];
  failed: Stage[];
  next: string | null;
  asks: Ask[];
  stages: Stage[];
}
export function report(
  job: JobView,
  group: ContactGroup,
  all: Stage[],
): Report {
  const own = all
    .filter((stage) => group.rounds.some((round) => belongs(stage, round)))
    .sort((a, b) => at(a) - at(b));
  const state = text(job.job.pipeline_state);
  const asks: Ask[] = [];
  if (group.ambiguous)
    asks.push({
      text: "核对多条尚未结束的联系记录",
      detail: "确认后才能判断这个岗位的当前进展。",
    });
  for (const stage of own.filter((s) => s.status === "waiting"))
    asks.push({
      text:
        asksByPhase[stage.runPhase] ||
        asksByActivity[stage.event.activity] ||
        `处理“${label(stage.event.activity)}”的等待事项`,
      detail:
        typeof stage.event.message === "string" ? stage.event.message : null,
    });
  if (text(filterOf(job)?.decision) === "review") {
    const reasons = filterOf(job)?.reasons;
    asks.push({
      text: "判断基本要求中待核对的条件",
      detail: Array.isArray(reasons)
        ? reasons.map((r) => text(record(r)?.message)).join("；") || null
        : null,
    });
  }
  if (job.meta.paused === true)
    asks.push({
      text: "岗位已暂停，决定是否继续",
      detail:
        typeof job.meta.pause_reason === "string"
          ? job.meta.pause_reason
          : null,
    });
  if (state === "interview_pending" && !group.ambiguous)
    asks.push({
      text: "准备并参加面试",
      detail: "记录中没有面试时间，请以平台消息为准。",
    });
  const current = own.filter((s) =>
    ["started", "heartbeat"].includes(s.status),
  );
  const planned = own
    .map((s) => s.event)
    .filter((e) => typeof e.next_step === "string" && e.next_step.length > 0)
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at))[0];
  const lane: Lane = closed(job)
    ? "closed"
    : asks.length
      ? "needs"
      : current.length
        ? "active"
        : waitingForOther.has(state)
          ? "waiting"
          : "idle";
  const reason = job.job.state_reason;
  return {
    lane,
    milestone: group.ambiguous
      ? "有多条进行中的联系记录，当前进展待核对"
      : (milestones[state] || label(state)) +
        (closed(job) && reason ? `（${label(reason)}）` : ""),
    milestoneAt: group.ambiguous ? null : job.job.state_changed_at,
    done: own.filter((s) => s.status === "completed"),
    current,
    unconfirmed: own.filter((s) => s.status === "unconfirmed"),
    failed: own.filter((s) => s.status === "failed"),
    next: closed(job) ? null : planned ? text(planned.next_step) : null,
    asks: asks.filter(
      (ask, index) =>
        asks.findIndex((other) => other.text === ask.text) === index,
    ),
    stages: own,
  };
}
