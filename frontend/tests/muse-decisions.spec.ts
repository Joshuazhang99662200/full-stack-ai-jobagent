import { test, expect } from "@playwright/test";
import { QueryClient } from "@tanstack/react-query";
import { saveExactDecision } from "../src/muse/decisions";
import type { MuseActions } from "../src/muse/contracts";

const ORIGINAL = "您好，这是供审核的合成招呼语。";
const EDITED = "您好，这是改过的合成招呼语。";

function fakeApi(opts: { draftFollowsEdit: boolean; saveError?: string | null }) {
  let draft = ORIGINAL;
  const decisions: { id: number }[] = [];
  const calls: string[] = [];
  const api = {
    saveGreetingDraft: async ({ text }: { text: string }) => {
      calls.push("save");
      if (opts.saveError)
        return { ok: false, error: opts.saveError, message: "未知", signalRecorded: false };
      if (opts.draftFollowsEdit) draft = text;
      return {
        ok: true,
        error: null,
        message: "已保存你的修改意见，需要重新生成并复核后再审批，没有发送权。",
        signalRecorded: true,
      };
    },
    recordDecision: async () => {
      calls.push("decide");
      decisions.push({ id: decisions.length + 1 });
      return { ok: true, error: null, message: "已批准", decisionId: decisions.length, writebackStarted: false };
    },
    getJob: async () => ({ draftGreeting: draft, decisions }),
  } as unknown as MuseActions;
  return { api, calls };
}

const request = {
  rank: 7,
  kind: "accept_original" as const,
  note: null,
  original: ORIGINAL,
  text: EDITED,
};

test("an edit the host keeps as revision feedback is never approved", async () => {
  const { api, calls } = fakeApi({ draftFollowsEdit: false });
  const r = await saveExactDecision(api, new QueryClient(), request);
  expect(r.status).toBe("revised");
  expect(r.message).toContain("重新生成并复核");
  expect(calls).toEqual(["save"]);
});

test("an edit the host saves as the new draft is approved with exactly that text", async () => {
  const { api, calls } = fakeApi({ draftFollowsEdit: true });
  const r = await saveExactDecision(api, new QueryClient(), request);
  expect(r.status).toBe("saved");
  expect(calls).toEqual(["save", "decide"]);
});

test("an unknown save outcome stops before any approval", async () => {
  const { api, calls } = fakeApi({ draftFollowsEdit: true, saveError: "outcome_unknown" });
  const r = await saveExactDecision(api, new QueryClient(), request);
  expect(r.status).toBe("unknown");
  expect(calls).toEqual(["save"]);
});
