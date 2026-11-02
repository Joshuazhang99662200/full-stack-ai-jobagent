import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };
import { createDemoSource } from "../src/demoHost";
import { createMuseActions } from "../src/muse/adapter";
import { createSnapshotSource } from "../src/dataSource";

async function setup() {
  let saved: string | null = null;
  const source = await createDemoSource({
    snapshot: structuredClone(demo),
    definitions: {},
    storage: {
      load: () => saved,
      save: (v) => {
        saved = v;
      },
    },
  });
  const journal = new Map<string, string>();
  const options = {
    operationStore: {
      load: (k: string) => journal.get(k) ?? null,
      save: (k: string, v: string) => {
        journal.set(k, v);
      },
    },
  };
  const api = createMuseActions(source, options);
  const todo = (await api.getTodos({})).jobs[0];
  return { source, api, options, rank: todo.rank };
}

test("Muse revision feedback uses the existing named personal option and retains its full note", async () => {
  const { source, api, rank } = await setup();
  const r = await api.recordDecision({
    rank,
    kind: "accept_revise",
    greetingText: null,
    note: "请保留已核实经历，修改开头。",
  });
  expect(r.ok).toBe(true);
  const state = await source.getHostState();
  expect(state.jobs[0].events.at(-1)?.kind).toBe("answer_todo");
  expect(state.jobs[0].events.at(-1)?.detail).toContain("修改开头");
  expect(state.batches).toHaveLength(0);
});

test("Muse unknown decision survives adapter recreation and only reads the same operation", async () => {
  const { source, api, options, rank } = await setup();
  let writes = 0,
    reads = 0;
  source.recordDecision = async () => {
    writes++;
    throw new Error("interrupted");
  };
  source.getOperation = async (key) => {
    reads++;
    return {
      operation_key: key,
      status: "unknown",
      message: "待核验",
      event_id: null,
    };
  };
  const request = {
    rank,
    kind: "accept_original" as const,
    greetingText: null,
    note: null,
  };
  expect((await api.recordDecision(request)).error).toBe("outcome_unknown");
  const restored = createMuseActions(source, options);
  expect((await restored.recordDecision(request)).error).toBe(
    "outcome_unknown",
  );
  expect(writes).toBe(1);
  expect(reads).toBe(1);
});

test("Muse approval and exact batch confirmation remain separate and require verified readback", async () => {
  const { api, rank, source } = await setup();
  expect((await api.createJobExecutionBatch({ rank })).items).toHaveLength(0);
  expect(
    (
      await api.recordDecision({
        rank,
        kind: "accept_original",
        greetingText: null,
        note: null,
      })
    ).ok,
  ).toBe(true);
  expect(
    (await source.getHostState()).batches.every((b) => b.items.length === 0),
  ).toBe(true);
  const batch = await api.createJobExecutionBatch({ rank });
  expect(batch.batchId).not.toBeNull();
  expect((await api.confirmExecution({ batchId: batch.batchId! })).ok).toBe(
    true,
  );
  expect(
    (await api.getBatch({ batchId: batch.batchId! })).items[0].status,
  ).toBe("done");
  expect((await api.confirmExecution({ batchId: batch.batchId! })).ok).toBe(
    false,
  );
});

test("readonly Muse view preserves unknown personal-source diagnostics and has no write authority", async () => {
  const api = createMuseActions(createSnapshotSource(structuredClone(demo)), {
    operationStore: {
      load: () => null,
      save: () => {
        throw new Error("no writes");
      },
    },
  });
  const rank = (await api.getTableData({})).rows[0].rank;
  expect(
    (
      await api.recordDecision({
        rank,
        kind: "accept_original",
        note: null,
        greetingText: null,
      })
    ).error,
  ).toBe("not_integrated");
  expect((await api.getExecPrecheck({ rank })).executable).toBe(false);
});
