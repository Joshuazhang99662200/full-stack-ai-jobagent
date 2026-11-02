import { checkSnapshot, type ConsoleDataSource } from "../dataSource";
import type { JobView, Snapshot } from "../contracts";
import type {
  HostJob,
  HostMaterial,
  HostDecisionRequest,
  HostBatch,
} from "../hostContracts";
import {
  currentMaterial,
  displayHistory,
  hasVerifiedReadback,
  latestDecision,
  personalTodos,
} from "../hostService";
import { channelOf } from "../channels";
import type { MuseActions, ApiResponse } from "./contracts";

type Response<K extends keyof MuseActions> = ApiResponse<MuseActions, K>;
type MaterialItem = Response<"getJobMaterials">["sentGreetings"][number];
export interface MuseOperationStore {
  load(key: string): string | null;
  save(key: string, value: string): void;
}
export interface MuseAdapterOptions {
  operationStore: MuseOperationStore;
}
const value = (v: unknown) => (typeof v === "string" ? v : "");
const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
const failed = (message: string) => ({
  ok: false,
  error: "not_integrated",
  message,
});
const hash = (v: string) => {
  let n = 2166136261;
  for (const c of v) n = Math.imul(n ^ c.charCodeAt(0), 16777619);
  return n >>> 0;
};

/** Translate source RPC views only. Canonical state and all side effects stay in host services. */
export function createMuseActions(
  source: ConsoleDataSource,
  options: MuseAdapterOptions,
): MuseActions {
  const identities = new Map<number, string>();
  const batches = new Map<number, string>();
  let verifiedContacts = new Set<string>();
  function batchNumber(id: string) {
    let key = hash(id) || 1;
    while (batches.has(key) && batches.get(key) !== id) key++;
    batches.set(key, id);
    return key;
  }
  async function data() {
    const snapshot = checkSnapshot(await source.getSnapshot());
    const state = await source.getHostState();
    if (
      source.mode !== "snapshot" &&
      state.candidate_id !== snapshot.candidate_id
    )
      throw new Error("候选人范围不匹配");
    for (const j of snapshot.jobs) {
      const id = String(j.job.pipeline_id);
      const supplied = Number(j.meta.host_rank ?? j.job.host_rank);
      let rank =
        Number.isInteger(supplied) && supplied > 0 ? supplied : hash(id) || 1;
      while (identities.has(rank) && identities.get(rank) !== id) rank++;
      identities.set(rank, id);
    }
    for (const batch of state.batches) batchNumber(batch.batch_id);
    verifiedContacts = new Set(
      state.batches
        .flatMap((b) => b.items)
        .filter(hasVerifiedReadback)
        .map((i) => i.contact_id),
    );
    return { snapshot, state };
  }
  function rankOf(job: JobView) {
    return [...identities].find(([, id]) => id === job.job.pipeline_id)![0];
  }
  async function context(rank: number) {
    const { snapshot, state } = await data();
    const job = snapshot.jobs.find(
      (j) => j.job.pipeline_id === identities.get(rank),
    );
    if (!job) throw new Error("岗位来源尚未接入或已变化");
    const entry = state.jobs.find(
      (j) =>
        j.job_id === job.job.job_id && j.contact_id === job.job.pipeline_id,
    );
    return {
      snapshot,
      state,
      job,
      entry,
      material: entry && currentMaterial(entry),
    };
  }
  function stateOf(job: JobView, entry?: HostJob) {
    const latest = entry && latestDecision(entry);
    if (latest?.kind === "decline") return "declined";
    if (job.job.pipeline_state === "abandoned") return "closed";
    if (
      verifiedContacts.has(String(job.job.pipeline_id)) ||
      value(job.job.sent_greeting) ||
      [
        "greeting_sent",
        "greeting_read",
        "initial_contact",
        "resume_requested",
        "resume_sent",
        "interview_pending",
        "interviewed",
      ].includes(String(job.job.pipeline_state))
    )
      return channelOf(job).greetings ? "sent" : "delivered";
    if (
      entry &&
      latest?.kind === "approve_material" &&
      latest.material?.revision === currentMaterial(entry)?.revision
    )
      return channelOf(job).greetings ? "pending_greeting" : "pending_delivery";
    return "pending_review";
  }
  function facts(
    job: JobView,
    entry?: HostJob,
  ): Response<"getJob">["job"] & {} {
    const state = stateOf(job, entry);
    return {
      rank: rankOf(job),
      platform: channelOf(job).name,
      title: value(job.job.title),
      company: value(job.job.company),
      location: value(job.job.location) || null,
      salary: value(job.job.salary_raw) || null,
      jobUrl: value(job.job.job_url) || null,
      hostStatus: state,
      state,
      stateLabel:
        (
          {
            pending_review: "待审阅",
            pending_greeting: "已批准待发送",
            pending_delivery: "已批准待投递",
            sent: "已发送",
            delivered: "已投递",
            declined: "已放弃",
            closed: "已结束",
          } as Record<string, string>
        )[state] ?? "待核对",
      group: ["closed", "declined"].includes(state)
        ? "closed"
        : ["sent", "delivered"].includes(state)
          ? "done"
          : "pending",
      blocked: !!entry?.blockers.length,
      blockedKind: entry?.blockers.length ? "host" : null,
      blockedNote: entry?.blockers.join("；") || null,
      hasDraft: !!(
        (entry && currentMaterial(entry)?.body) ||
        value(job.job.draft_greeting)
      ),
      deliveryResult: null,
      latestDecisionKind: entry ? (latestDecision(entry)?.kind ?? null) : null,
      historyCount: job.history.length + (entry?.events.length ?? 0),
    };
  }
  const decisionKind = (kind: string, job: JobView) =>
    (
      ({
        approve_material: channelOf(job).greetings
          ? "accept_original"
          : "deliver",
        save_draft: "accept_revise",
        answer_todo: "skip",
      }) as Record<string, string>
    )[kind] ?? kind;
  async function record(
    rank: number,
    kind: HostDecisionRequest["kind"],
    body: string,
    note: string,
    intent: string,
    answer?: { todo_id: string; option_id: string },
  ) {
    const c = await context(rank);
    if (!c.entry || !c.material || !source.recordDecision)
      return {
        ...failed("当前选择尚未接入保存服务，请在对话中告知。"),
        decisionId: null,
        writebackStarted: false,
      };
    const fingerprint = JSON.stringify([
      c.snapshot.candidate_id,
      c.job.job.pipeline_id,
      c.material.revision,
      intent,
      body,
      note,
      answer ?? null,
    ]);
    const key = `muse.intent.${c.snapshot.candidate_id}.${hash(fingerprint)}`;
    let previous = options.operationStore.load(key);
    const operationKey = previous
      ? (JSON.parse(previous).operationKey as string)
      : crypto.randomUUID();
    if (!previous) {
      options.operationStore.save(
        key,
        JSON.stringify({ operationKey, fingerprint }),
      );
    } else if (JSON.parse(previous).fingerprint !== fingerprint)
      throw new Error("操作键冲突，已停止写入");
    let receipt;
    try {
      receipt = previous
        ? await source.getOperation?.(operationKey)
        : await source.recordDecision({
            candidate_id: c.snapshot.candidate_id,
            job_id: String(c.job.job.job_id),
            contact_id: String(c.job.job.pipeline_id),
            operation_key: operationKey,
            kind,
            material_revision: c.material.revision,
            body,
            attachment_digests: c.material.attachments.map((a) => a.digest),
            note,
            todo_id: answer?.todo_id ?? null,
            option_id: answer?.option_id ?? null,
          });
    } catch {
      receipt = undefined;
    }
    if (!receipt || receipt.status === "unknown")
      return {
        ok: true,
        error: "outcome_unknown",
        message: "保存结果未知，请先核验，不要重复提交。",
        decisionId: null,
        writebackStarted: false,
      };
    if (receipt.status !== "saved")
      return {
        ...failed(receipt.message),
        decisionId: null,
        writebackStarted: false,
      };
    const fresh = await context(rank);
    const index =
      fresh.entry?.events.findIndex((e) => e.event_id === receipt.event_id) ??
      -1;
    return {
      ok: true,
      error: null,
      message: receipt.message,
      decisionId: index < 0 ? null : index + 1,
      writebackStarted: false,
    };
  }
  async function echo(
    batch: HostBatch,
    snapshot: Snapshot,
  ): Promise<Response<"createExecutionBatch">> {
    const batchId = batchNumber(batch.batch_id);
    batches.set(batchId, batch.batch_id);
    return {
      batchId,
      status: batch.status,
      items: batch.items.map((item) => {
        const job = snapshot.jobs.find(
          (j) => j.job.pipeline_id === item.contact_id,
        )!;
        return {
          rank: rankOf(job),
          kind: channelOf(job).greetings ? "greeting" : "delivery",
          title: item.title,
          company: value(job.job.company),
          platform: item.channel,
          greetingPreview: item.material.body || null,
        };
      }),
      excluded: batch.excluded.map((e) => ({
        rank: rankOf(snapshot.jobs.find((j) => j.job.job_id === e.job_id)!),
        reason: e.reason,
      })),
    };
  }
  const actions: MuseActions = {
    getTableData: async () => {
      const { snapshot, state } = await data();
      return {
        rows: snapshot.jobs.map((job) => {
          const entry = state.jobs.find(
              (j) => j.contact_id === job.job.pipeline_id,
            ),
            f = facts(job, entry);
          const bullets = [
            ...strings(job.match_result?.strengths),
            ...strings(job.match_result?.partial_matches),
            ...strings(job.match_result?.uncertainties),
          ];
          return {
            rank: f.rank,
            title: f.title,
            company: f.company,
            platform: f.platform,
            channel: f.platform,
            location: f.location,
            salary: f.salary,
            jobUrl: f.jobUrl,
            matchBullets: bullets.length
              ? bullets
              : ["已保存的匹配理由尚未接入"],
            matchScore:
              typeof job.match_result?.overall === "number"
                ? job.match_result.overall
                : null,
            progress: entry?.progress ?? null,
            progressStale: !entry?.progress,
            progressError: null,
            progressUpdatedAt: null,
            state: f.state,
            intakeAt: entry?.intake_at ?? null,
            contacted: ["sent", "delivered"].includes(f.state),
            waiting: ["sent", "delivered"].includes(f.state),
          };
        }),
        pendingProgress: 0,
        failedProgress: 0,
      };
    },
    getJob: async ({ rank }) => {
      const c = await context(rank),
        { job, entry, material } = c;
      return {
        job: facts(job, entry),
        jdPoints: strings(job.job.jd_points).length
          ? strings(job.job.jd_points)
          : value(job.job.jd_text).split(/\n+/).filter(Boolean),
        gaps: strings(job.job.gaps),
        draftGreeting:
          (material?.body ?? value(job.job.draft_greeting)) || null,
        approvedGreeting:
          entry && latestDecision(entry)?.kind === "approve_material"
            ? (latestDecision(entry)?.material?.body ?? null)
            : null,
        draftVersion: material?.label ?? null,
        completeness: value(job.job.completeness) || null,
        matchStrengths: strings(job.match_result?.strengths),
        matchPartial: strings(job.match_result?.partial_matches),
        matchUncertainties: strings(job.match_result?.uncertainties),
        matchHardGaps: strings(job.match_result?.hard_gaps),
        hardFilterReasons: [],
        sendStatus: stateOf(job, entry) === "sent" ? "sent" : null,
        deliveryStatus:
          stateOf(job, entry) === "delivered" ? "delivered" : null,
        progress: entry?.progress ?? null,
        progressStale: !entry?.progress,
        progressError: null,
        channel: channelOf(job).name,
        matchLabel: "已存评估",
        matchScore:
          typeof job.match_result?.overall === "number"
            ? job.match_result.overall
            : null,
        decisions: (entry?.events ?? []).map((e, index) => ({
          id: index + 1,
          kind: decisionKind(e.kind, job),
          note: e.detail || null,
          greetingText: e.material?.body ?? null,
          status: "recorded",
          createdAt: e.occurred_at,
        })),
        history: job.history.map((e, index) => ({
          id: index + 1,
          eventKind: String(e.to_state ?? "recorded"),
          occurredAt: value(e.changed_at) || null,
          occurredAtStatus: e.changed_at ? "已记录" : "时间未记录",
          detail: value(e.reason),
          isTransition: true,
          origin: "host",
        })),
      };
    },
    getJobMaterials: async ({ rank }) => {
      const { job, entry, state } = await context(rank);
      const item = (m: HostMaterial, index: number): MaterialItem => ({
        id: index + 1,
        title: m.label,
        body: m.body,
        occurredAt: null,
        source: null,
      });
      const sentGreetings: MaterialItem[] = [];
      if (value(job.job.sent_greeting))
        sentGreetings.push({
          id: 1,
          title: "实际发送",
          body: value(job.job.sent_greeting),
          occurredAt: null,
          source: "已存发送记录",
        });
      for (const b of state.batches)
        for (const i of b.items)
          if (
            i.contact_id === job.job.pipeline_id &&
            hasVerifiedReadback(i) &&
            !sentGreetings.some((s) => s.body === i.material.body)
          )
            sentGreetings.push({
              id: sentGreetings.length + 1,
              title: "实际发送",
              body: i.material.body,
              occurredAt: i.readback!.observed_at,
              source: "已核验逐项回读",
            });
      return {
        sentGreetings,
        greetingVersions: (entry?.materials ?? []).map(item),
        feedback: displayHistory(entry?.events ?? []).map((e, index) => ({
          id: index + 1,
          title: decisionKind(e.kind, job),
          body: e.detail,
          occurredAt: e.occurred_at,
          source: null,
        })),
        panelSync: [],
        deliveries: [],
        cvFiles: (entry?.materials ?? [])
          .flatMap((m) =>
            m.attachments.map((a) => ({
              title: a.name,
              body: m.label,
              occurredAt: null,
              source: a.url,
            })),
          )
          .map((a, index) => ({ ...a, id: index + 1 })),
        commSnapshots: [],
      };
    },
    getTodos: async () => {
      const { snapshot, state } = await data();
      if (state.sync.status === "unavailable")
        throw new Error("个人待办来源尚未接入");
      const grouped = new Map<number, Response<"getTodos">["jobs"][number]>();
      for (const todo of personalTodos(state)) {
        const job = snapshot.jobs.find(
          (j) => j.job.pipeline_id === todo.contact_id,
        );
        if (!job) continue;
        const rank = rankOf(job);
        let current = grouped.get(rank);
        if (!current) {
          current = {
            rank,
            title: value(job.job.title),
            company: value(job.job.company),
            platform: channelOf(job).name,
            location: value(job.job.location) || null,
            salary: value(job.job.salary_raw) || null,
            matchOverall:
              typeof job.match_result?.overall === "number"
                ? job.match_result.overall
                : null,
            matchStrengths: strings(job.match_result?.strengths),
            matchPartial: strings(job.match_result?.partial_matches),
            matchUncertainties: strings(job.match_result?.uncertainties),
            items: [],
          };
          grouped.set(rank, current);
        }
        current.items.push({
          id: todo.todo_id,
          kind: channelOf(job).greetings ? "greeting" : "review",
          action: channelOf(job).greetings ? "看看招呼语" : "确认岗位条件",
          question: todo.question,
          reasons: todo.basis,
        });
      }
      const jobs = [...grouped.values()];
      return {
        jobCount: jobs.length,
        itemCount: jobs.reduce((n, j) => n + j.items.length, 0),
        jobs,
      };
    },
    getBatch: async ({ batchId }) => {
      const { snapshot, state } = await data();
      const batch = state.batches.find(
        (b) => b.batch_id === batches.get(batchId),
      );
      if (!batch) return { batch: null, items: [] };
      return {
        batch: {
          id: batchId,
          status: batch.status === "completed" ? "done" : batch.status,
          createdAt: "时间未记录",
        },
        items: batch.items.map((i) => {
          const job = snapshot.jobs.find(
            (j) => j.job.pipeline_id === i.contact_id,
          )!;
          return {
            rank: rankOf(job),
            kind: channelOf(job).greetings ? "greeting" : "delivery",
            status: hasVerifiedReadback(i)
              ? "done"
              : i.status === "verified"
                ? "unknown"
                : i.status,
            detail: i.readback?.detail ?? null,
            title: i.title,
            company: value(job.job.company),
            platform: i.channel,
          };
        }),
      };
    },
    getChannelLogin: async () => ({
      channels: (await data()).state.channels.map((c) => ({
        channel: c.label,
        status: c.status === "connected" ? "ok" : c.status,
        checkedAt: c.checked_at,
        restoreRequestedAt: c.restore_requested_at,
        restoreStatus: c.restore_requested_at ? "recorded" : "none",
      })),
    }),
    getConsoleSnapshot: async () => {
      const { snapshot, state } = await data();
      return {
        seeded: true,
        matchComplete: snapshot.jobs.every((j) => !!j.match_result),
        queueReconcileNeeded: false,
        matchCount: snapshot.jobs.filter((j) => j.match_result).length,
        hardCounts: {},
        lastImport: null,
        snapshot: {
          ...snapshot,
          jobs: snapshot.jobs.map((j) => {
            const entry = state.jobs.find(
              (e) => e.contact_id === j.job.pipeline_id,
            );
            return {
              ...j,
              job: {
                ...j.job,
                host_rank: rankOf(j),
                host_status: stateOf(j, entry),
                send_status: stateOf(j, entry) === "sent" ? "sent" : null,
                delivery_status:
                  stateOf(j, entry) === "delivered" ? "delivered" : null,
              },
              match_result: j.match_result ?? null,
              match_context: j.match_context ?? null,
              hard_filter_result: j.hard_filter_result ?? null,
              hard_filter_context: j.hard_filter_context ?? null,
            };
          }),
        },
      };
    },
    getReviewBrief: async ({ rank }) => {
      const c = await context(rank);
      return {
        points: strings(c.job.job.jd_points).length
          ? strings(c.job.job.jd_points)
          : value(c.job.job.jd_text).split(/\n+/).filter(Boolean),
        keywords: strings(c.job.job.keywords),
        incomplete: false,
        note: null,
      };
    },
    getExecPrecheck: async ({ rank }) => {
      const { job, entry, material } = await context(rank),
        f = facts(job, entry);
      const available =
        !!source.createExecutionBatch && !!source.confirmExecution;
      const block =
        entry?.blockers.join("；") ||
        (!available
          ? "执行服务尚未接入"
          : !channelOf(job).greetings
            ? "当前渠道获批附件传输尚未接入"
            : f.state === "sent" || f.state === "delivered"
              ? "该联系轮次已经执行，需先核对记录"
              : null);
      return {
        found: true,
        rank,
        platform: f.platform,
        channel: f.platform,
        title: f.title,
        company: f.company,
        location: f.location,
        salary: f.salary,
        kind: channelOf(job).greetings ? "greeting" : "delivery",
        state: f.state,
        approved:
          f.state === "pending_greeting" || f.state === "pending_delivery",
        needsApproval: f.state === "pending_review",
        executable: !block,
        greetingText: material?.body ?? null,
        blockReason: block,
        familyRanks: [],
      };
    },
    getOnlineResume: async () => {
      throw new Error("实际在线简历来源尚未接入");
    },
    getRecoveryReport: async () => ({
      seeded: false,
      itemCount: 0,
      report: { status: "not_integrated" },
    }),
    recordDecision: async (req) => {
      const c = await context(req.rank);
      if (req.kind === "accept_revise" || req.kind === "skip") {
        const optionId = req.kind === "accept_revise" ? "revise" : "hold";
        const todo = personalTodos(c.state).find(
          (t) =>
            t.contact_id === c.job.job.pipeline_id &&
            t.material_revision === c.material?.revision &&
            t.options.some((o) => o.option_id === optionId),
        );
        if (!todo)
          return {
            ...failed("当前材料没有接入这一项反馈选项，请交给宿主处理。"),
            decisionId: null,
            writebackStarted: false,
          };
        return record(
          req.rank,
          "answer_todo",
          c.material?.body ?? "",
          req.note ?? "",
          req.kind,
          { todo_id: todo.todo_id, option_id: optionId },
        );
      }
      const kinds: Partial<
        Record<typeof req.kind, HostDecisionRequest["kind"]>
      > = {
        approve_text: "approve_text",
        accept_original: "approve_material",
        deliver: "approve_material",
        decline: "decline",
      };
      const kind = kinds[req.kind];
      if (!kind)
        return {
          ...failed("该宿主决定类型尚未接入，请在对话中告知。"),
          decisionId: null,
          writebackStarted: false,
        };
      return record(
        req.rank,
        kind,
        req.greetingText ?? c.material?.body ?? "",
        req.note ?? "",
        req.kind,
      );
    },
    saveGreetingDraft: async ({ rank, text }) => {
      const r = await record(
        rank,
        "save_draft",
        text,
        "保存修改",
        "save_draft",
      );
      return {
        ok: r.ok && r.error !== "outcome_unknown",
        error: r.error,
        message: r.message,
      };
    },
    createExecutionBatch: async () => {
      const { snapshot, state } = await data();
      if (!source.createExecutionBatch)
        return {
          batchId: null,
          status: "unavailable",
          items: [],
          excluded: [],
        };
      return echo(
        await source.createExecutionBatch(state.jobs.map((j) => j.contact_id)),
        snapshot,
      );
    },
    createJobExecutionBatch: async ({ rank }) => {
      const c = await context(rank);
      if (!source.createExecutionBatch)
        return {
          batchId: null,
          status: "unavailable",
          items: [],
          excluded: [{ rank, reason: "执行服务尚未接入" }],
        };
      return echo(
        await source.createExecutionBatch([String(c.job.job.pipeline_id)]),
        c.snapshot,
      );
    },
    confirmExecution: async ({ batchId }) => {
      const { snapshot } = await data();
      const id = batches.get(batchId),
        batch = id && (await source.getBatch(id));
      if (!batch || !source.confirmExecution)
        return { ...failed("执行服务尚未接入"), taskStarted: false };
      if (batch.status !== "ready")
        return {
          ...failed("该批次已进入执行或结果未知，请先核验，不能重复执行。"),
          taskStarted: false,
        };
      const key = `muse.execution.${snapshot.candidate_id}.${batch.batch_id}`;
      const old = options.operationStore.load(key);
      if (old)
        return {
          ...failed("执行请求已有记录，请先核验，不能重复执行。"),
          error: "outcome_unknown",
          taskStarted: false,
        };
      const operationKey = crypto.randomUUID();
      options.operationStore.save(key, operationKey);
      try {
        const result = await source.confirmExecution({
          candidate_id: snapshot.candidate_id,
          operation_key: operationKey,
          batch_id: batch.batch_id,
          selected: batch.items.map((i) => ({
            item_id: i.item_id,
            material_revision: i.material.revision,
            body: i.material.body,
            attachment_digests: i.material.attachments.map((a) => a.digest),
          })),
        });
        return {
          ok: result.status === "saved",
          error:
            result.status === "unknown"
              ? "outcome_unknown"
              : result.status === "rejected"
                ? "rejected"
                : null,
          message: result.message,
          taskStarted: false,
        };
      } catch {
        return {
          ...failed("执行结果未知，请先核验，不要重复执行。"),
          error: "outcome_unknown",
          taskStarted: false,
        };
      }
    },
    syncFromHost: async () => {
      if (!source.synchronize)
        return {
          started: false,
          message: "宿主同步尚未接入，当前仅重新读取本地记录。",
        };
      const r = await source.synchronize();
      return { started: r.status === "current", message: r.message };
    },
    requestLoginRestore: async ({ channel }) => {
      const c = (await data()).state.channels.find(
        (c) => c.channel === channel || c.label === channel,
      );
      if (!c || !source.requestLoginRestore)
        return {
          ...failed("登录恢复请求服务尚未接入"),
          requestedAt: null,
          requestId: null,
          taskStarted: false,
        };
      const r = await source.requestLoginRestore(c.channel);
      const current = (await data()).state.channels.find(
        (x) => x.channel === c.channel,
      )!;
      return {
        ok: r.status === "saved",
        error: r.status === "unknown" ? "outcome_unknown" : null,
        message: r.message,
        requestedAt: current.restore_requested_at,
        requestId: r.operation_key,
        taskStarted: false,
      };
    },
    generateProgress: async () => ({
      generated: 0,
      corrected: 0,
      remaining: 0,
      failures: [
        { rank: 0, reason: "进展生成服务尚未接入，请由宿主按已确认配置提供。" },
      ],
    }),
    seedFromSnapshot: async () => {
      throw new Error("前端不能导入或播种宿主队列");
    },
    repairMatchFromSnapshot: async () => {
      throw new Error("前端不能修复宿主匹配记录");
    },
    reconcileToQueue: async () => {
      throw new Error("前端不能重写宿主队列");
    },
    syncNewJobs: async () => {
      throw new Error("前端不能自动导入特定轮次岗位");
    },
  };
  return actions;
}
