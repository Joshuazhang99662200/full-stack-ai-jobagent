import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { Console } from "../lib/console.js";

// No fake location/history globals: embedding must work without a browser.
const snapshot = JSON.parse(
  await readFile(new URL("../src/demo.json", import.meta.url), "utf8"),
);
const rendered = renderToString(
  createElement(Console, { snapshot, initialView: "runs" }),
);
assert.ok(rendered.includes("岗位进展"));
assert.ok(rendered.includes("RUN_AAAAAAAA"));
assert.ok(rendered.includes("这里显示助手记录的工作过程"));
const empty = renderToString(
  createElement(Console, {
    initialView: "runs",
    snapshot: {
      ...snapshot,
      runs: [],
      sources: [{ name: "harness", status: "complete", message: null }],
    },
  }),
);
assert.ok(empty.includes("还没有运行记录"));
console.log(
  "SSR embedding and empty-state smoke passed without browser globals.",
);

const { MusePanel } = await import("../muse-lib/muse.js");
const muse = renderToString(createElement(MusePanel, { actions: {} }));
assert.ok(muse.includes("muse-space"));
assert.ok(muse.includes("读取求职队列中"));
const current = renderToString(
  createElement(MusePanel, { actions: {}, appearance: "current" }),
);
assert.ok(current.includes("任务进度"));
assert.ok(current.includes("muse-current"));
console.log("Muse default and current template SSR smoke passed without browser globals.");
