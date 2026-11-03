import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };
import { createDemoSource } from "../src/demoHost";
import { createMuseActions } from "../src/muse/adapter";

test("quick execution rejects changed exact content even when a host reuses its revision label", async () => {
  const { api, source, rank } = await setup();
  await api.recordDecision({
    rank,
    kind: "accept_original",
    greetingText: null,
    note: null,
  });
  const read = source.getHostState;
  let calls = 0;
  source.getHostState = async () => {
    const state = await read();
    state.jobs[0].materials.at(-1)!.body += " 未批准的修改";
    return state;
  };
  source.confirmExecution = async (req) => {
    calls++;
    return {
      operation_key: req.operation_key,
      status: "unknown",
      message: "不应执行",
      event_id: null,
    };
  };
  const result = await api.executeSelectionDirect({});
  expect(result.queued).toHaveLength(0);
  await api.toggleSelectionItem({ rank, selected: true });
  const blocked = await api.executeSelectionDirect({});
  expect(blocked.queued).toHaveLength(0);
  expect(blocked.excluded.map((e) => e.reason).join("；")).toContain("批准");
  expect(calls).toBe(0);
});

test("verified success alone removes selection and failure todo reflects recorded cause", async () => {
  const { api, rank } = await setup();
  await api.recordDecision({
    rank,
    kind: "accept_original",
    greetingText: null,
    note: null,
  });
  await api.toggleSelectionItem({ rank, selected: true });
  await api.executeSelectionDirect({});
  await expect
    .poll(async () => (await api.getSelectionQueue({})).count)
    .toBe(0);
  await api.toggleSelectionItem({ rank, selected: true });
  expect((await api.getSelectionQueue({})).count).toBe(1);
  expect(
    (await api.executeSelectionDirect({})).excluded
      .map((e) => e.reason)
      .join("；"),
  ).toContain("已经执行");
  const failed = await setup(true);
  await failed.api.recordDecision({
    rank: failed.rank,
    kind: "accept_original",
    greetingText: null,
    note: null,
  });
  await failed.api.toggleSelectionItem({ rank: failed.rank, selected: true });
  await failed.api.executeSelectionDirect({});
  await expect
    .poll(async () =>
      (await failed.api.getTodos({})).jobs.some((j) =>
        j.items.some(
          (i) =>
            i.kind === "failure" &&
            i.reasons.some((r) => r.includes("登录已失效")),
        ),
      ),
    )
    .toBe(true);
});

async function setup(fail = false) {
  let saved: string | null = null;
  const store = new Map<string, string>();
  const source = await createDemoSource({
    snapshot: structuredClone(demo),
    definitions: {},
    storage: {
      load: () => saved,
      save: (v) => {
        saved = v;
      },
    },
    ...(fail
      ? {
          readback: async () => ({
            status: "failed" as const,
            detail: "合成平台原文：登录已失效",
            evidence: null,
            material_revision: null,
            observed_at: "2026-11-03T00:00:00+08:00",
          }),
        }
      : {}),
  });
  const options = {
    operationStore: {
      load: (k: string) => store.get(k) ?? null,
      save: (k: string, v: string) => {
        store.set(k, v);
      },
    },
  };
  const api = createMuseActions(source, options);
  const rank = (await api.getTodos({})).jobs[0].rank;
  return { source, api, options, rank };
}
test("persistent selection inversion affects only visible ranks and survives adapter recreation", async () => {
  const { api, source, options, rank } = await setup();
  await api.toggleSelectionItem({ rank, selected: true });
  const other = (await api.getTableData({})).rows.find(
    (r) => r.rank !== rank,
  )!.rank;
  await api.applySelectionOperation({
    operation: "invert_visible",
    visibleRanks: [rank, other],
  });
  expect(
    (await createMuseActions(source, options).getSelectionQueue({})).ranks,
  ).toEqual([other]);
});
test("quick execution rejects unapproved material without inventing approval and records exclusion", async () => {
  const { api, source, rank } = await setup();
  await api.toggleSelectionItem({ rank, selected: true });
  const r = await api.executeSelectionDirect({});
  expect(r.queued).toHaveLength(0);
  expect(r.excluded[0].reason).toContain("批准");
  expect((await source.getHostState()).jobs[0].events).toHaveLength(0);
  expect((await api.getSelectionQueue({})).ranks).toContain(rank);
  expect(
    (await api.getJob({ rank })).history.some(
      (h) => h.eventKind === "execution_skipped",
    ),
  ).toBe(true);
});
test("failed readback stays selected, keeps raw reason, counts once, and can be explicitly retried", async () => {
  const { api, rank } = await setup(true);
  await api.recordDecision({
    rank,
    kind: "accept_original",
    greetingText: null,
    note: null,
  });
  await api.toggleSelectionItem({ rank, selected: true });
  await api.executeSelectionDirect({});
  await expect
    .poll(async () => (await api.getJob({ rank })).execFailures.jobCount)
    .toBe(1);
  expect((await api.getJob({ rank })).execFailures.lastReason).toBe(
    "合成平台原文：登录已失效",
  );
  expect((await api.getSelectionQueue({})).ranks).toContain(rank);
  await api.executeJobDirect({ rank });
  await expect
    .poll(async () => (await api.getJob({ rank })).execFailures.jobCount)
    .toBe(2);
});
test("unknown dispatch is never automatically retried", async () => {
  const { api, source, rank } = await setup();
  let calls = 0;
  source.confirmExecution = async () => {
    calls++;
    throw new Error("interrupted");
  };
  await api.recordDecision({
    rank,
    kind: "accept_original",
    greetingText: null,
    note: null,
  });
  await api.toggleSelectionItem({ rank, selected: true });
  await api.executeSelectionDirect({});
  await expect.poll(() => calls).toBe(1);
  expect((await api.executeJobDirect({ rank })).ok).toBe(false);
  expect(calls).toBe(1);
});
test("manual edit signals retain complete before and after text, while viewing produces none", async () => {
  const { api, rank } = await setup();
  const before = (await api.getJob({ rank })).draftGreeting!;
  expect((await api.getGreetingSignals({ rank })).count).toBe(0);
  await api.saveGreetingDraft({ rank, text: before + " 合成修改。" });
  const signals = await api.getGreetingSignals({ rank });
  expect(signals.count).toBe(1);
  expect(signals.signals[0].beforeText).toBe(before);
  expect(signals.signals[0].afterText).toBe(before + " 合成修改。");
});
