import { expect, test } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };
import { createDemoSource } from "../src/demoHost";
import { createSnapshotSource } from "../src/dataSource";
import {
  mergeJobFacts,
  synchronizeHost,
  personalTodos,
  displayHistory,
} from "../src/hostService";

const clock = () => "2026-11-02T10:00:00+08:00";
const memory = () => {
  let data: string | null = null;
  return {
    load: () => data,
    save: (value: string) => {
      data = value;
    },
  };
};
async function setup() {
  const storage = memory();
  const source = await createDemoSource({
    snapshot: demo,
    definitions: {},
    storage,
    clock,
  });
  const state = await source.getHostState();
  const job = state.jobs[0],
    material = job.materials.at(-1)!;
  const request = {
    candidate_id: state.candidate_id,
    job_id: job.job_id,
    contact_id: job.contact_id,
    operation_key: "OP_A",
    kind: "approve_material" as const,
    material_revision: material.revision,
    body: material.body,
    attachment_digests: material.attachments.map((a) => a.digest),
    note: "Confirmed exact synthetic material",
    todo_id: null,
    option_id: null,
  };
  return { source, storage, state, job, material, request };
}

test("snapshot source and demo expose the same read interface; readonly has no writes", async () => {
  const { source } = await setup();
  const readonly = createSnapshotSource(demo, {});
  for (const current of [readonly, source]) {
    expect((await current.getSnapshot()).candidate_id).toBe(demo.candidate_id);
    expect(
      (await current.getJob("DEMO_A", "PIPE_AAAAAAAAAAAAAAAA"))?.job.job_id,
    ).toBe("DEMO_A");
    expect(await current.getTodos()).toBeInstanceOf(Array);
    expect(await current.getChannelLogin()).toBeInstanceOf(Array);
    expect(await current.getBatch("MISSING")).toBeNull();
  }
  expect(readonly.recordDecision).toBeUndefined();
});

test("decision is idempotent, durable, append-only and does not execute", async () => {
  const { source, storage, request } = await setup();
  const first = await source.recordDecision!(request);
  expect(first.status).toBe("saved");
  expect(await source.recordDecision!(request)).toEqual(first);
  expect(
    (await source.recordDecision!({ ...request, body: "Changed" })).status,
  ).toBe("rejected");
  const resumed = await createDemoSource({
    snapshot: demo,
    definitions: {},
    storage,
    clock,
  });
  expect((await resumed.getHostState()).jobs[0].events).toHaveLength(1);
  expect((await resumed.getHostState()).batches).toHaveLength(0);
  await resumed.recordDecision!({
    ...request,
    operation_key: "OP_B",
    kind: "approve_text",
  });
  expect((await resumed.getHostState()).jobs[0].events).toHaveLength(2);
});

test("candidate and contact isolation reject cross-scope decisions", async () => {
  const { source, request } = await setup();
  for (const change of [
    { candidate_id: "CAND_OTHER" },
    { contact_id: "PIPE_OTHER" },
  ])
    expect(
      (await source.recordDecision!({ ...request, ...change })).status,
    ).toBe("rejected");
  expect((await source.getHostState()).jobs[0].events).toHaveLength(0);
});

test("save failure stays unknown, does not commit memory and never automatically retries", async () => {
  const { request } = await setup();
  let saves = 0;
  const source = await createDemoSource({
    snapshot: demo,
    definitions: {},
    clock,
    storage: {
      load: () => null,
      save: () => {
        saves++;
        throw new Error("offline");
      },
    },
  });
  expect((await source.recordDecision!(request)).status).toBe("unknown");
  expect((await source.recordDecision!(request)).status).toBe("unknown");
  expect(saves).toBe(1);
  expect((await source.getHostState()).jobs[0].events).toHaveLength(0);
  expect((await source.getOperation!(request.operation_key)).status).toBe(
    "unknown",
  );
});

test("changed materials invalidate approval and leave a concrete personal todo", async () => {
  const { source, request } = await setup();
  await source.recordDecision!(request);
  await source.recordDecision!({
    ...request,
    operation_key: "EDIT",
    kind: "save_draft",
    body: "New exact synthetic material",
  });
  expect((await source.getHostState()).jobs[0].materials).toHaveLength(2);
  expect(
    (await source.recordDecision!({ ...request, operation_key: "OLD" })).status,
  ).toBe("rejected");
  expect(
    (await source.getTodos()).filter((t) => t.status === "pending"),
  ).toHaveLength(1);
  expect(
    (await source.createExecutionBatch!([request.contact_id])).items,
  ).toHaveLength(0);
});

test("execution selection binds exact content; no selection or missing readback never succeeds", async () => {
  const { source, request, job } = await setup();
  await source.recordDecision!(request);
  const batch = await source.createExecutionBatch!([job.contact_id]);
  expect(batch.items).toHaveLength(1);
  const item = batch.items[0];
  const selection = {
    item_id: item.item_id,
    material_revision: item.material.revision,
    body: item.material.body,
    attachment_digests: item.material.attachments.map((a) => a.digest),
  };
  const input = {
    candidate_id: "CAND_DEMO",
    operation_key: "EXEC_A",
    batch_id: batch.batch_id,
    selected: [selection],
  };
  expect(
    (await source.confirmExecution!({ ...input, selected: [] })).status,
  ).toBe("rejected");
  expect(
    (
      await source.confirmExecution!({
        ...input,
        selected: [{ ...selection, body: "tampered" }],
      })
    ).status,
  ).toBe("rejected");
  expect((await source.confirmExecution!(input)).status).toBe("saved");
  const result = await source.getBatch(batch.batch_id);
  expect(result!.items[0].status).toBe("verified");
  expect(result!.items[0].readback!.evidence).toContain("SYNTHETIC");
  expect((await source.getSnapshot()).jobs[0].job.pipeline_state).toBe(
    "draft_pending",
  );
  expect(
    (await source.createExecutionBatch!([job.contact_id])).items,
  ).toHaveLength(0);
});

test("absent positive readback remains unknown and blocks another execution", async () => {
  const { storage, request, job } = await setup();
  const source = await createDemoSource({
    snapshot: demo,
    definitions: {},
    storage,
    clock,
    readback: async () => ({
      status: "unknown",
      detail: "No positive evidence",
      evidence: null,
      material_revision: null,
      observed_at: null,
    }),
  });
  await source.recordDecision!(request);
  const batch = await source.createExecutionBatch!([job.contact_id]),
    item = batch.items[0];
  await source.confirmExecution!({
    candidate_id: "CAND_DEMO",
    operation_key: "EXEC_UNKNOWN",
    batch_id: batch.batch_id,
    selected: [
      {
        item_id: item.item_id,
        material_revision: item.material.revision,
        body: item.material.body,
        attachment_digests: [],
      },
    ],
  });
  expect((await source.getBatch(batch.batch_id))!.items[0].status).toBe(
    "unknown",
  );
  expect(
    (await source.createExecutionBatch!([job.contact_id])).items,
  ).toHaveLength(0);
});

test("login restoration records one timestamp per dropped channel without a browser action", async () => {
  const { source } = await setup();
  const dropped = (await source.getChannelLogin()).find(
    (c) => c.status === "dropped",
  )!;
  const first = await source.requestLoginRestore!(dropped.channel);
  expect(await source.requestLoginRestore!(dropped.channel)).toEqual(first);
  expect(
    (await source.getChannelLogin()).find((c) => c.channel === dropped.channel)!
      .status,
  ).toBe("dropped");
  expect((await source.getHostState()).receipts).toHaveLength(1);
});

test("field sync preserves decisions and execution fields from stale snapshots", async () => {
  const previous = {
    ...demo.jobs[0],
    job: {
      ...demo.jobs[0].job,
      pipeline_state: "greeting_sent",
      sent_greeting: "Verified sent text",
    },
  };
  const incoming = {
    ...demo.jobs[0],
    job: {
      ...demo.jobs[0].job,
      title: "New scraped title",
      pipeline_state: "draft_pending",
    },
  };
  const merged = mergeJobFacts(previous, incoming);
  expect(merged.job.title).toBe("New scraped title");
  expect(merged.job.sent_greeting).toBe("Verified sent text");
  expect(merged.job.pipeline_state).toBe("greeting_sent");
});

test("sync follows readback/import/export/recount order and lists mismatching jobs", async () => {
  const order: string[] = [];
  const result = await synchronizeHost(
    {
      readPlatform: async () => {
        order.push("readback");
      },
      importHostFacts: async () => {
        order.push("import");
      },
      exportPanelRecords: async () => {
        order.push("export");
      },
      compareCounts: async () => {
        order.push("recount");
        return [
          { job_id: "DEMO_A", title: "合成岗位", detail: "待核对数量不同" },
        ];
      },
    },
    clock,
  );
  expect(order).toEqual(["readback", "import", "export", "recount"]);
  expect(result.status).toBe("mismatch");
  expect(result.differences[0].job_id).toBe("DEMO_A");
});

test("corrupt persisted demo is an error and does not silently reseed", async () => {
  await expect(
    createDemoSource({
      snapshot: demo,
      definitions: {},
      storage: { load: () => "broken", save: () => {} },
      clock,
    }),
  ).rejects.toThrow();
});

test("an older batch cannot execute after a newer material is approved", async () => {
  const { source, request } = await setup();
  await source.recordDecision!(request);
  const batch = await source.createExecutionBatch!([request.contact_id]);
  await source.recordDecision!({
    ...request,
    kind: "save_draft",
    body: "Replacement material",
    operation_key: "NEW_DRAFT",
  });
  const material = (await source.getHostState()).jobs[0].materials.at(-1)!;
  await source.recordDecision!({
    ...request,
    material_revision: material.revision,
    body: material.body,
    operation_key: "NEW_APPROVAL",
  });
  const item = batch.items[0];
  const result = await source.confirmExecution!({
    candidate_id: "CAND_DEMO",
    operation_key: "STALE_EXEC",
    batch_id: batch.batch_id,
    selected: [
      {
        item_id: item.item_id,
        material_revision: item.material.revision,
        body: item.material.body,
        attachment_digests: [],
      },
    ],
  });
  expect(result.status).toBe("rejected");
  expect((await source.getBatch(batch.batch_id))!.items[0].readback).toBeNull();
});

test("a stale writer cannot overwrite a newer append-only decision", async () => {
  const { source, storage, request } = await setup();
  const other = await createDemoSource({
    snapshot: demo,
    definitions: {},
    storage,
    clock,
  });
  await source.recordDecision!(request);
  expect(
    (
      await other.recordDecision!({
        ...request,
        operation_key: "OTHER",
        kind: "decline",
      })
    ).status,
  ).not.toBe("saved");
  const resumed = await createDemoSource({
    snapshot: demo,
    definitions: {},
    storage,
    clock,
  });
  expect((await resumed.getHostState()).jobs[0].events[0].kind).toBe(
    "approve_material",
  );
});

test("execution excludes already contacted and paused jobs rather than reopening them", async () => {
  const { source, state, request } = await setup();
  const contacted = state.jobs[1],
    material = contacted.materials.at(-1)!;
  await source.recordDecision!({
    ...request,
    job_id: contacted.job_id,
    contact_id: contacted.contact_id,
    material_revision: material.revision,
    body: material.body,
    operation_key: "CONTACTED_APPROVAL",
  });
  expect(
    (await source.createExecutionBatch!([contacted.contact_id])).items,
  ).toHaveLength(0);
});

test("a partial selection retains unselected plans and never reads them back", async () => {
  const snapshot = structuredClone(demo);
  snapshot.jobs[1].job.pipeline_state = "draft_pending";
  snapshot.jobs[1].history = snapshot.jobs[1].history.filter(
    (e) => e.to_state === "draft_pending",
  );
  snapshot.jobs[1].meta.paused = false;
  const storage = memory();
  let calls = 0;
  const source = await createDemoSource({
    snapshot,
    definitions: {},
    storage,
    clock,
    readback: async (item) => {
      calls++;
      return {
        status: "verified",
        evidence: "SYNTHETIC_READBACK",
        material_revision: item.material.revision,
        observed_at: clock(),
        detail: "synthetic",
      };
    },
  });
  const state = await source.getHostState();
  for (const job of state.jobs.slice(0, 2)) {
    const material = job.materials.at(-1)!;
    await source.recordDecision!({
      candidate_id: state.candidate_id,
      job_id: job.job_id,
      contact_id: job.contact_id,
      material_revision: material.revision,
      body: material.body,
      attachment_digests: [],
      operation_key: job.job_id,
      kind: "approve_material",
      note: "synthetic",
      todo_id: null,
      option_id: null,
    });
  }
  const batch = await source.createExecutionBatch!(
    state.jobs.slice(0, 2).map((j) => j.contact_id),
  );
  expect(batch.items).toHaveLength(2);
  const item = batch.items[0];
  await source.confirmExecution!({
    candidate_id: "CAND_DEMO",
    operation_key: "ONE_ONLY",
    batch_id: batch.batch_id,
    selected: [
      {
        item_id: item.item_id,
        material_revision: item.material.revision,
        body: item.material.body,
        attachment_digests: [],
      },
    ],
  });
  const result = await source.getBatch(batch.batch_id);
  expect(calls).toBe(1);
  expect(result!.items).toHaveLength(2);
  expect(result!.items[1].readback).toBeNull();
});

test("stale personal material remains pending until the current version is reviewed", async () => {
  const { state } = await setup();
  state.todos[0].material_revision = "OLD_SYNTHETIC_REVISION";
  expect(personalTodos(state)).toHaveLength(1);
});

test("display deduplication preserves authoritative raw events", async () => {
  const { source, request } = await setup();
  await source.recordDecision!(request);
  const state = await source.getHostState();
  const original = state.jobs[0].events[0];
  const events = [original, { ...original, event_id: "DUPLICATE_EVENT" }];
  expect(displayHistory(events)).toHaveLength(1);
  expect(events).toHaveLength(2);
  expect(displayHistory(events)[0].event_id).toBe("DUPLICATE_EVENT");
});
