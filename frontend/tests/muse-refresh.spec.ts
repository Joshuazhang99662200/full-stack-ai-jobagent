import { test, expect } from "@playwright/test";
import { QueryClient } from "@tanstack/react-query";
import { refreshAfterWrite } from "../src/muse/refresh";

const keys = {
  snapshot: ["console-snapshot"],
  table: ["table-data"],
  todos: ["todos"],
  channels: ["channel-login"],
  selection: ["selection-queue"],
  job7: ["job", 7],
  materials7: ["job-materials", 7],
  signals7: ["greeting-signals", 7],
  precheck7: ["exec-precheck", 7],
  job8: ["job", 8],
  materials8: ["job-materials", 8],
  batch3: ["batch", 3],
  batch4: ["batch", 4],
} as const;

function seeded() {
  const client = new QueryClient();
  for (const key of Object.values(keys)) client.setQueryData([...key], { seeded: true });
  return client;
}

function invalidated(client: QueryClient) {
  return Object.entries(keys)
    .filter(([, key]) => client.getQueryState([...key])?.isInvalidated)
    .map(([name]) => name)
    .sort();
}

test("a job-scoped write refreshes only that job, the list rows and todos", async () => {
  const client = seeded();
  await refreshAfterWrite(client, { ranks: [7] });
  expect(invalidated(client)).toEqual(
    ["materials7", "job7", "precheck7", "signals7", "table", "todos"].sort(),
  );
});

test("an execution submit also refreshes its batch and the selection queue", async () => {
  const client = seeded();
  await refreshAfterWrite(client, { ranks: [7, 8], batchId: 3, selection: true });
  expect(invalidated(client)).toEqual(
    [
      "batch3",
      "job7",
      "job8",
      "materials7",
      "materials8",
      "precheck7",
      "selection",
      "signals7",
      "table",
      "todos",
    ].sort(),
  );
});

test("the full snapshot and channel login are never refetched by an ordinary write", async () => {
  const client = seeded();
  await refreshAfterWrite(client, { ranks: [], batchId: null, selection: false });
  expect(invalidated(client)).toEqual(["table", "todos"]);
});
