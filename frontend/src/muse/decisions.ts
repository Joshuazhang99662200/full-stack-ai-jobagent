import type { QueryClient } from "@tanstack/react-query";
import type { MuseActions, MuseRecordDecisionRequest } from "./contracts";

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
    await client.invalidateQueries();
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
