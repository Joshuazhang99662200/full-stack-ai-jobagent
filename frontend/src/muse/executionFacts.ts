import type { HostState } from "../hostContracts";
import { hasVerifiedReadback } from "../hostService";

/** A view of recorded attempts, never a new canonical job state or reconstructed history. */
export function executionFacts(
  state: HostState,
  contactId: string,
  channel: string,
) {
  const attempts = state.batches
    .flatMap((b) => b.items)
    .filter((i) => i.selected);
  const own = attempts.filter((i) => i.contact_id === contactId),
    last = own.at(-1);
  const failed = attempts.filter(
    (i) =>
      i.status === "failed" &&
      i.readback?.status === "failed" &&
      !!i.readback.detail.trim(),
  );
  const failures = failed.filter((i) => i.contact_id === contactId);
  return {
    status: !last
      ? "pending"
      : hasVerifiedReadback(last)
        ? "done"
        : last.status === "running"
          ? "executing"
          : last.status === "failed" && !!last.readback?.detail.trim()
            ? "failed"
            : "unknown",
    detail: last?.readback?.detail ?? null,
    archive: {
      jobCount: failures.length,
      channelCount: failed.filter((i) => i.channel === channel).length,
      channel,
      lastReason: failures.at(-1)?.readback?.detail ?? null,
      lastAt: failures.at(-1)?.readback?.observed_at ?? null,
      recent: failures
        .map((i, index) => ({
          id: index + 1,
          kind: i.channel.includes("猎聘") ? "delivery" : "greeting",
          reason: i.readback!.detail,
          batchId: null,
          createdAt: i.readback?.observed_at ?? "时间未记录",
        }))
        .reverse(),
    },
  };
}
