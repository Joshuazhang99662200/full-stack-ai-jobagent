import type { Definitions, Snapshot } from "./contracts";
import type { ConsoleDataSource } from "./dataSource";
import { checkSnapshot } from "./dataSource";
import type {
  HostBatch,
  HostChannel,
  HostDecisionRequest,
  HostEvent,
  HostExecutionItem,
  HostMaterial,
  HostReadback,
  HostReceipt,
  HostState,
} from "./hostContracts";
import {
  currentMaterial,
  latestDecision,
  personalTodos,
  mergeJobFacts,
  synchronizeHost,
} from "./hostService";
import { channelOf } from "./channels";

export interface DemoStorage {
  load(): string | null;
  save(value: string): void;
}
interface Options {
  snapshot: Snapshot;
  definitions: Definitions;
  storage: DemoStorage;
  clock?: () => string;
  readback?: (item: HostExecutionItem) => Promise<HostReadback>;
}
interface Stored {
  state: HostState;
  requests: Record<string, string>;
}
const copy = <T>(value: T): T => structuredClone(value);
const digests = (material: HostMaterial) =>
  material.attachments.map((a) => a.digest);
const same = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b);
async function revision(body: string, files: string[]) {
  const data = new TextEncoder().encode(JSON.stringify([body, files]));
  const hash = await crypto.subtle.digest("SHA-256", data);
  return (
    "sha256:" +
    [...new Uint8Array(hash)]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
  );
}

/** Explicit synthetic-only adapter. It cannot call a recruitment platform or a host task. */
export async function createDemoSource(
  options: Options,
): Promise<ConsoleDataSource> {
  const snapshot = copy(checkSnapshot(options.snapshot));
  if (snapshot.candidate_id !== "CAND_DEMO")
    throw new Error("合成适配器只允许合成候选人");
  const clock = options.clock ?? (() => new Date().toISOString());
  const raw = options.storage.load();
  let persistedRaw = raw;
  let saved: Stored;
  if (raw !== null) {
    saved = JSON.parse(raw);
    if (
      saved.state?.protocol_version !== "1.0" ||
      saved.state.candidate_id !== snapshot.candidate_id ||
      !Array.isArray(saved.state.jobs) ||
      !Array.isArray(saved.state.receipts) ||
      !saved.requests ||
      saved.state.jobs.some(
        (j) =>
          !snapshot.jobs.some(
            (s) =>
              s.job.job_id === j.job_id && s.job.pipeline_id === j.contact_id,
          ),
      )
    )
      throw new Error("合成存储版本或候选人不匹配，请在排查时核对存储");
  } else {
    const jobs = await Promise.all(
      snapshot.jobs.map(async (entry) => {
        const body = String(entry.job.draft_greeting ?? "");
        return {
          job_id: String(entry.job.job_id),
          contact_id: String(entry.job.pipeline_id),
          materials: [
            {
              revision: await revision(body, []),
              label: "初稿（合成）",
              body,
              attachments: [],
            },
          ],
          events: [],
          blockers:
            entry.job.pipeline_state === "abandoned"
              ? ["这个岗位已经结束"]
              : [],
          progress: null,
          intake_at:
            typeof entry.job.created_at === "string"
              ? entry.job.created_at
              : null,
        };
      }),
    );
    const first = jobs[0];
    const channels: HostChannel[] = [
      ...new Map(
        snapshot.jobs.map((j) => [channelOf(j).name, channelOf(j).name]),
      ).values(),
    ].map((name) => ({
      channel: name,
      label: name,
      status: "connected",
      checked_at: clock(),
      restore_requested_at: null,
    }));
    channels.push({
      channel: "SYNTHETIC_OFFLINE",
      label: "示例离线渠道",
      status: "dropped",
      checked_at: clock(),
      restore_requested_at: null,
    });
    saved = {
      requests: {},
      state: {
        protocol_version: "1.0",
        candidate_id: snapshot.candidate_id,
        jobs,
        todos: first
          ? [
              {
                todo_id: "SYNTHETIC_TODO_A",
                job_id: first.job_id,
                contact_id: first.contact_id,
                question: "这份材料是否可以继续推进？",
                material_revision: first.materials[0].revision,
                requires_person: true,
                host_resolved: true,
                basis: ["合成岗位要求已核对；此处只演示本人对材料的选择。"],
                options: [
                  {
                    option_id: "revise",
                    label: "先修改",
                    consequence: "记录修改意见，交给助手准备新版后再审阅。",
                  },
                  {
                    option_id: "hold",
                    label: "暂缓推进",
                    consequence: "记录暂缓决定，本轮不执行。",
                  },
                ],
                status: "pending",
                result: null,
              },
            ]
          : [],
        channels,
        batches: [],
        receipts: [],
        sync: {
          status: "stale",
          message: "合成记录尚未做同步核对。",
          checked_at: null,
          differences: [],
        },
      },
    };
  }
  let serial: Promise<unknown> = Promise.resolve();
  const unknown = new Map<string, HostReceipt>();
  function enqueue<T>(task: () => Promise<T>): Promise<T> {
    const guarded = () =>
      typeof navigator !== "undefined" && navigator.locks
        ? navigator.locks.request(
            `ja-console.demo.writer.${snapshot.candidate_id}`,
            task,
          )
        : task();
    const next = serial.then(guarded);
    serial = next.catch(() => {});
    return next;
  }
  function persist(next: Stored) {
    if (options.storage.load() !== persistedRaw)
      throw new Error("STALE_WRITER");
    const encoded = JSON.stringify(next);
    options.storage.save(encoded);
    saved = next;
    persistedRaw = encoded;
  }
  function readLatest() {
    const value = options.storage.load();
    if (value !== persistedRaw && value !== null) {
      const next = JSON.parse(value) as Stored;
      if (
        next.state?.candidate_id !== snapshot.candidate_id ||
        next.state.protocol_version !== "1.0"
      )
        throw new Error("合成存储范围已变化");
      saved = next;
      persistedRaw = value;
    }
  }
  const receipt = (
    key: string,
    status: HostReceipt["status"],
    message: string,
    eventId: string | null = null,
  ): HostReceipt => ({
    operation_key: key,
    status,
    message,
    event_id: eventId,
  });
  async function commit(next: Stored, result: HostReceipt, request: unknown) {
    next.requests[result.operation_key] = JSON.stringify(request);
    next.state.receipts.push(result);
    try {
      persist(next);
      return copy(result);
    } catch (error) {
      if (error instanceof Error && error.message === "STALE_WRITER")
        return receipt(
          result.operation_key,
          "rejected",
          "另一个窗口已保存新记录，请刷新后核对。",
        );
      const resultUnknown = receipt(
        result.operation_key,
        "unknown",
        "保存结果未确认，请先核验，不要重复操作。",
      );
      unknown.set(result.operation_key, resultUnknown);
      return resultUnknown;
    }
  }
  function replay(key: string, input: unknown) {
    if (unknown.has(key)) return copy(unknown.get(key)!);
    const existing = saved.state.receipts.find((r) => r.operation_key === key);
    if (existing)
      return same(saved.requests[key], JSON.stringify(input))
        ? copy(existing)
        : receipt(key, "rejected", "同一操作记录的内容发生变化，请核对。");
    return null;
  }
  function check(input: HostDecisionRequest, state = saved.state) {
    const job = state.jobs.find(
      (j) => j.job_id === input.job_id && j.contact_id === input.contact_id,
    );
    const material = job && currentMaterial(job);
    return input.candidate_id === state.candidate_id &&
      job &&
      material &&
      material.revision === input.material_revision &&
      same(digests(material), input.attachment_digests)
      ? { job, material }
      : null;
  }
  function append(
    job: HostState["jobs"][number],
    key: string,
    kind: string,
    detail: string,
    material: HostMaterial | null,
  ): HostEvent {
    const event = {
      event_id: crypto.randomUUID(),
      operation_key: key,
      job_id: job.job_id,
      contact_id: job.contact_id,
      kind,
      detail,
      material: copy(material),
      occurred_at: clock(),
    };
    job.events.push(event);
    return event;
  }
  function precheck(contactId: string): string | null {
    const job = saved.state.jobs.find((j) => j.contact_id === contactId);
    const original = snapshot.jobs.find((j) => j.job.pipeline_id === contactId);
    if (!job || !original) return "岗位来源未接入";
    if (
      original.job.pipeline_state !== "draft_pending" ||
      original.history.some((e) => e.to_state !== "draft_pending")
    )
      return "该联系轮次已有业务进展，不能重新执行首次联系";
    if (original.meta.paused === true) return "这个岗位已经暂停";
    if (job.blockers.length) return job.blockers.join("；");
    if (!channelOf(original).greetings) return "当前渠道的获批附件传输尚未接入";
    const channel = saved.state.channels.find(
      (c) => c.channel === channelOf(original).name,
    );
    if (channel?.status !== "connected") return "需要先核对渠道登录";
    if (
      saved.state.batches.some((b) =>
        b.items.some(
          (i) =>
            i.contact_id === contactId &&
            ["running", "verified", "unknown"].includes(i.status),
        ),
      )
    )
      return "已有执行记录，需先核对结果";
    const decision = latestDecision(job);
    if (
      !decision ||
      decision.kind !== "approve_material" ||
      decision.material?.revision !== currentMaterial(job)?.revision
    )
      return "这份材料尚未获本人批准或已变更";
    return null;
  }
  const source: ConsoleDataSource = {
    mode: "demo",
    getSnapshot: async () => copy(snapshot),
    getDefinitions: async () => copy(options.definitions),
    getJob: async (jobId, contactId) =>
      copy(
        snapshot.jobs.find(
          (j) => j.job.job_id === jobId && j.job.pipeline_id === contactId,
        ) ?? null,
      ),
    getMaterials: async (jobId, contactId) =>
      copy(
        saved.state.jobs.find(
          (j) => j.job_id === jobId && j.contact_id === contactId,
        )?.materials ?? [],
      ),
    getHostState: async () => {
      readLatest();
      return copy(saved.state);
    },
    getTodos: async () => {
      readLatest();
      return copy(saved.state.todos);
    },
    getChannelLogin: async () => {
      readLatest();
      return copy(saved.state.channels);
    },
    getBatch: async (id) => {
      readLatest();
      return copy(saved.state.batches.find((b) => b.batch_id === id) ?? null);
    },
    getOperation: async (key) => {
      const stored = options.storage.load();
      if (stored !== null) {
        const state = JSON.parse(stored) as Stored;
        if (state.state?.candidate_id === saved.state.candidate_id) {
          const found = state.state.receipts.find(
            (r) => r.operation_key === key,
          );
          if (found) {
            saved = state;
            persistedRaw = stored;
            unknown.delete(key);
            return copy(found);
          }
        }
      }
      return copy(
        saved.state.receipts.find((r) => r.operation_key === key) ??
          receipt(key, "unknown", "尚无可核实的保存结果，请勿重复操作。"),
      );
    },
    recordDecision: (input) =>
      enqueue(async () => {
        const duplicate = replay(input.operation_key, input);
        if (duplicate) return duplicate;
        const next = copy(saved),
          found = check(input, next.state);
        if (!found)
          return receipt(
            input.operation_key,
            "rejected",
            "岗位、联系轮次或材料已变更，请重新读取后审阅。",
          );
        const { job, material } = found;
        if (input.kind !== "save_draft" && input.body !== material.body)
          return receipt(
            input.operation_key,
            "rejected",
            "请先保存修改后的草稿，再审阅新材料。",
          );
        let eventMaterial = material;
        if (input.kind === "save_draft") {
          if (input.body === material.body)
            return receipt(input.operation_key, "rejected", "正文没有变化。");
          eventMaterial = {
            ...copy(material),
            body: input.body,
            revision: await revision(input.body, digests(material)),
            label: `修订稿 ${job.materials.length + 1}（合成）`,
          };
          job.materials.push(eventMaterial);
          for (const todo of next.state.todos.filter(
            (t) => t.contact_id === job.contact_id,
          )) {
            todo.status = "pending";
            todo.result = "材料已变化，请重新审阅新版。";
            todo.material_revision = eventMaterial.revision;
          }
        }
        if (input.kind === "answer_todo") {
          const todo = personalTodos(next.state).find(
            (t) =>
              t.todo_id === input.todo_id && t.contact_id === input.contact_id,
          );
          const option = todo?.options.find(
            (o) => o.option_id === input.option_id,
          );
          if (!todo || !option)
            return receipt(
              input.operation_key,
              "rejected",
              "待办已变化，请重新核对。",
            );
          todo.status = "resolved";
          todo.result = `${option.label}：${option.consequence}`;
          if (option.option_id === "hold")
            job.blockers.push("本人决定暂缓推进");
        }
        if (["approve_material", "decline"].includes(input.kind))
          for (const todo of next.state.todos.filter(
            (t) =>
              t.contact_id === job.contact_id &&
              t.material_revision === material.revision,
          )) {
            todo.status = "resolved";
            todo.result =
              input.kind === "decline"
                ? "已记录放弃决定"
                : "已记录材料批准，尚未执行";
          }
        const event = append(
          job,
          input.operation_key,
          input.kind,
          input.note || "本人保存了材料决定",
          eventMaterial,
        );
        return commit(
          next,
          receipt(
            input.operation_key,
            "saved",
            "已保存决定，未触发发送或投递。",
            event.event_id,
          ),
          input,
        );
      }),
    createExecutionBatch: (contacts) =>
      enqueue(async () => {
        const next = copy(saved);
        const batch: HostBatch = {
          batch_id: crypto.randomUUID(),
          status: "ready",
          items: [],
          excluded: [],
        };
        for (const contact of new Set(contacts)) {
          const job = next.state.jobs.find((j) => j.contact_id === contact);
          const original = snapshot.jobs.find(
            (j) => j.job.pipeline_id === contact,
          );
          const reason = precheck(contact);
          if (reason || !job || !original) {
            batch.excluded.push({
              job_id: job?.job_id ?? contact,
              reason: reason ?? "来源缺失",
            });
            continue;
          }
          batch.items.push({
            item_id: crypto.randomUUID(),
            job_id: job.job_id,
            contact_id: contact,
            title: String(original.job.title),
            channel: channelOf(original).name,
            material: copy(currentMaterial(job)!),
            approval_event_id: latestDecision(job)!.event_id,
            status: "queued",
            readback: null,
            selected: false,
          });
        }
        next.state.batches.push(batch);
        persist(next);
        return copy(batch);
      }),
    confirmExecution: (input) =>
      enqueue(async () => {
        const duplicate = replay(input.operation_key, input);
        if (duplicate) return duplicate;
        const next = copy(saved),
          batch = next.state.batches.find((b) => b.batch_id === input.batch_id);
        const reject = () =>
          receipt(
            input.operation_key,
            "rejected",
            "清单、选择或材料已变化，需重新核对。",
          );
        if (
          input.candidate_id !== next.state.candidate_id ||
          !batch ||
          batch.status !== "ready" ||
          !input.selected.length ||
          new Set(input.selected.map((i) => i.item_id)).size !==
            input.selected.length
        )
          return reject();
        const selected: HostExecutionItem[] = [];
        for (const choice of input.selected) {
          const item = batch.items.find((i) => i.item_id === choice.item_id);
          const currentJob =
            item &&
            next.state.jobs.find((j) => j.contact_id === item.contact_id);
          if (
            !item ||
            precheck(item.contact_id) ||
            item.material.revision !== choice.material_revision ||
            !currentJob ||
            currentMaterial(currentJob)?.revision !== item.material.revision ||
            latestDecision(currentJob)?.event_id !== item.approval_event_id ||
            item.material.body !== choice.body ||
            !same(digests(item.material), choice.attachment_digests)
          )
            return reject();
          selected.push(item);
        }
        batch.status = "executing";
        for (const item of selected) {
          item.status = "running";
          item.selected = true;
        }
        const accepted = receipt(
          input.operation_key,
          "saved",
          "已记录所选清单，合成执行结果见逐条回读。",
        );
        const start = await commit(next, accepted, input);
        if (start.status !== "saved") return start;
        for (const selectedItem of selected) {
          const progress = copy(saved),
            runningBatch = progress.state.batches.find(
              (b) => b.batch_id === batch.batch_id,
            )!;
          const item = runningBatch.items.find(
            (i) => i.item_id === selectedItem.item_id,
          )!;
          let result: HostReadback;
          try {
            result = options.readback
              ? await options.readback(copy(item))
              : {
                  status: "verified",
                  detail: "合成平台逐项回读已核对；未访问真实渠道。",
                  evidence: `SYNTHETIC_READBACK_${item.item_id}`,
                  material_revision: item.material.revision,
                  observed_at: clock(),
                };
          } catch {
            result = {
              status: "unknown",
              detail: "回读未完成，需核验，不能重复执行。",
              evidence: null,
              material_revision: null,
              observed_at: null,
            };
          }
          if (
            result.status === "verified" &&
            (!result.evidence ||
              !result.observed_at ||
              result.material_revision !== item.material.revision)
          )
            result = {
              ...result,
              status: "unknown",
              detail: "回读缺少与当前材料一致的正向依据。",
            };
          item.readback = result;
          item.status = result.status;
          append(
            progress.state.jobs.find((j) => j.contact_id === item.contact_id)!,
            input.operation_key + ":" + item.item_id,
            "execution_readback",
            result.detail,
            item.material,
          );
          runningBatch.status = runningBatch.items.some(
            (i) => i.status === "running",
          )
            ? "executing"
            : runningBatch.items
                  .filter((i) => i.selected)
                  .every((i) => i.status === "verified")
              ? "completed"
              : runningBatch.items.some((i) => i.status === "unknown")
                ? "unknown"
                : "partial";
          try {
            persist(progress);
          } catch {
            return receipt(
              input.operation_key,
              "unknown",
              "执行回读保存未确认，需核验，不要重复执行。",
            );
          }
        }
        return copy(accepted);
      }),
    requestLoginRestore: (channel) =>
      enqueue(async () => {
        const key = `restore:${channel}`,
          existing = saved.state.receipts.find((r) => r.operation_key === key);
        if (existing) return copy(existing);
        if (unknown.has(key)) return copy(unknown.get(key)!);
        const next = copy(saved),
          entry = next.state.channels.find((c) => c.channel === channel);
        if (entry?.status !== "dropped")
          return receipt(
            key,
            "rejected",
            "仅在确认渠道掉线后才能记录恢复请求。",
          );
        entry.restore_requested_at = clock();
        return commit(
          next,
          receipt(
            key,
            "saved",
            "已记录恢复请求，等待宿主处理；尚未打开登录窗口。",
          ),
          { channel },
        );
      }),
    synchronize: () =>
      enqueue(async () => {
        // Two isolated synthetic sides exercise the same ownership and recount protocol.
        const hostFacts = copy(snapshot.jobs);
        let platformReadbacks: HostExecutionItem[] = [];
        let exported: HostEvent[] = [];
        const result = await synchronizeHost(
          {
            readPlatform: async () => {
              platformReadbacks = saved.state.batches
                .flatMap((b) => b.items)
                .filter(
                  (i) =>
                    i.readback?.status === "verified" &&
                    !!i.readback.evidence &&
                    !!i.readback.observed_at &&
                    i.readback.material_revision === i.material.revision,
                );
            },
            importHostFacts: async () => {
              snapshot.jobs = snapshot.jobs.map((previous) => {
                const incoming = hostFacts.find(
                  (j) => j.job.pipeline_id === previous.job.pipeline_id,
                );
                return incoming ? mergeJobFacts(previous, incoming) : previous;
              });
            },
            exportPanelRecords: async () => {
              exported = copy(
                saved.state.jobs
                  .flatMap((j) => j.events)
                  .filter(
                    (e) =>
                      e.kind !== "execution_readback" ||
                      platformReadbacks.some(
                        (i) =>
                          i.contact_id === e.contact_id &&
                          e.operation_key.endsWith(":" + i.item_id),
                      ),
                  ),
              );
            },
            compareCounts: async () =>
              saved.state.jobs.flatMap((job) => {
                const expected = job.events.filter(
                  (e) =>
                    e.kind !== "execution_readback" ||
                    platformReadbacks.some(
                      (i) =>
                        i.contact_id === e.contact_id &&
                        e.operation_key.endsWith(":" + i.item_id),
                    ),
                );
                const received = exported.filter(
                  (e) => e.contact_id === job.contact_id,
                );
                return same(expected, received)
                  ? []
                  : [
                      {
                        job_id: job.job_id,
                        title: String(
                          snapshot.jobs.find(
                            (j) => j.job.pipeline_id === job.contact_id,
                          )?.job.title ?? "待核对岗位",
                        ),
                        detail: "双方决定或已核验执行记录的数量不一致。",
                      },
                    ];
              }),
          },
          clock,
        );
        if (result.status === "current")
          result.message = "合成同步核对完成；未读取真实队列或真实渠道。";
        const next = copy(saved);
        next.state.sync = result;
        try {
          persist(next);
          return copy(result);
        } catch {
          return {
            ...result,
            status: "failed",
            message: "同步结果未保存，当前仍是旧记录。",
            checked_at: null,
          };
        }
      }),
  };
  return source;
}
