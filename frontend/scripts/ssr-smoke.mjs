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
assert.ok(rendered.includes("岗位任务队列"));
assert.ok(rendered.includes("RUN_AAAAAAAA"));
assert.ok(rendered.includes("宿主活动上报"));
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
assert.ok(empty.includes("当前候选人尚无运行记录"));
console.log(
  "SSR embedding and empty-state smoke passed without browser globals.",
);
