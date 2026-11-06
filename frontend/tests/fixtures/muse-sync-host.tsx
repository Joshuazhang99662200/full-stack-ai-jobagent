// Synthetic injected-host fixture. No AI/network/external action is performed.
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { createDemoSource } from "../../src/demoHost";
import { demo } from "../../src/demo";
import { createMuseActions } from "../../src/muse/adapter";
import { MusePanel } from "../../src/muse/MusePanel";
import type { MuseGetGreetingSignalsResponseSignalsItem } from "../../src/muse/contracts";

const store = new Map<string, string>();
let persisted: string | null = null;
const source = await createDemoSource({
  snapshot: structuredClone(demo),
  definitions: {},
  storage: {
    load: () => persisted,
    save: (value) => {
      persisted = value;
    },
  },
});
const api = createMuseActions(source, {
  operationStore: {
    load: (k) => store.get(k) ?? null,
    save: (k, v) => {
      store.set(k, v);
    },
  },
});
const rank = (await api.getTodos({})).jobs[0].rank;
await api.recordDecision({
  rank,
  kind: "accept_original",
  greetingText: null,
  note: null,
});
const signals: MuseGetGreetingSignalsResponseSignalsItem[] = [];
let resume: () => void = () => {};
const gate = new Promise<void>((resolve) => {
  resume = resolve;
});
Object.assign(window, {
  syncFixture: { resume: () => resume(), state: () => source.getHostState() },
});
api.regenerateGreeting = async ({ rank, currentText }) => {
  await gate;
  const before = (await api.getJob({ rank })).draftGreeting;
  if (currentText !== before) throw new Error("stale fixture text");
  const after = before + " 合成宿主生成的新版全文。";
  const r = await api.saveGreetingDraft({ rank, text: after });
  if (!r.ok) throw new Error("fixture save failed");
  signals.push({
    id: 1001,
    kind: "ai_regenerate",
    beforeText: new URLSearchParams(location.search).has("corrupt")
      ? null
      : before,
    afterText: after,
    createdAt: new Date().toISOString(),
  });
  return {
    ok: true,
    error: null,
    message: "合成宿主已保存新稿",
    greeting: after,
    signalRecorded: true,
  };
};
const manual = api.getGreetingSignals;
api.getGreetingSignals = async (request) => {
  const other = await manual(request);
  return {
    signals: [...signals, ...other.signals],
    count: signals.length + other.count,
  };
};
createRoot(document.getElementById("root")!).render(
  createElement(MusePanel, { actions: api, appearance: "current" }),
);
