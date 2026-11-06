import type { QueryClient } from "@tanstack/react-query";
import type { MuseActions, MuseRecordDecisionRequest } from "./contracts";
import { refreshAfterWrite } from "./refresh";

/** The zip's save -> fresh job -> decision-id readback sequence, exposed to the current view. */
export async function saveMuseDecision(
  api: MuseActions,
  client: QueryClient,
  request: MuseRecordDecisionRequest,
) {
  const result = await api.recordDecision(request);
  if (result.error === "outcome_unknown")
    return {
      status: "unknown" as const,
      message: result.message ?? "保存结果未知，请先核验，不要重复提交。",
    };
  if (!result.ok)
    return {
      status: "failed" as const,
      message: result.message ?? "决定没有保存成功。",
    };
  try {
    const fresh = await client.fetchQuery({
      queryKey: ["job", request.rank],
      queryFn: () => api.getJob({ rank: request.rank }),
    });
    if (
      result.decisionId == null ||
      !fresh.decisions.some((dec) => dec.id === result.decisionId)
    )
      return {
        status: "unknown" as const,
        message: "还不能确定决定有没有保存成功，先别重复提交。",
      };
    await refreshAfterWrite(client, { ranks: [request.rank] });
    return {
      status: "saved" as const,
      message: result.message ?? "已记录决定。",
    };
  } catch {
    return {
      status: "unknown" as const,
      message: "决定回读未完成，请先核验，不要重复提交。",
    };
  }
}

/**
 * Approval of an exact text. Edited words are saved first and read back; a host
 * that keeps the edit as revision feedback (the asked text stays unchanged until
 * it is regenerated and reviewed) returns "revised" and nothing is approved.
 */
export async function saveExactDecision(
  api: MuseActions,
  client: QueryClient,
  req: {
    rank: number;
    kind: MuseRecordDecisionRequest["kind"];
    note: string | null;
    original: string;
    text: string | null;
  },
): Promise<{
  status: "saved" | "revised" | "unknown" | "failed";
  message: string;
}> {
  const approving = req.kind === "accept_original";
  if (approving && req.text != null && req.text !== req.original) {
    const saved = await api.saveGreetingDraft({
      rank: req.rank,
      text: req.text,
    });
    if (!saved.ok)
      return {
        status: saved.error === "outcome_unknown" ? "unknown" : "failed",
        message: saved.message ?? "修改没有保存成功，还没有批准。",
      };
    const fresh = await api.getJob({ rank: req.rank });
    if (fresh.draftGreeting !== req.text) {
      await refreshAfterWrite(client, { ranks: [req.rank] });
      return {
        status: "revised",
        message:
          (saved.message ?? "修改已记为反馈。") +
          " 这份原文没有批准；新稿生成并复核后再批准。",
      };
    }
  }
  return saveMuseDecision(api, client, {
    rank: req.rank,
    kind: req.kind,
    note: req.note,
    greetingText: approving ? (req.text ?? req.original) : null,
  });
}
