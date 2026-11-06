import type { QueryClient } from "@tanstack/react-query";

export interface WriteScope {
  /** Jobs whose own records the write changed. */
  ranks?: readonly number[];
  /** Execution batch the write created or advanced. */
  batchId?: number | null;
  /** The write changed the persistent selection queue. */
  selection?: boolean;
}

const PER_JOB_KEYS = ["job", "job-materials", "greeting-signals", "exec-precheck"] as const;

/**
 * Refreshes only what an ordinary write can change: the touched jobs, the
 * list rows and the todo list. The full console snapshot and channel login
 * stay on their own schedule; a host sync is the one place that refreshes
 * everything.
 */
export async function refreshAfterWrite(client: QueryClient, scope: WriteScope = {}) {
  const keys: unknown[][] = [["table-data"], ["todos"]];
  for (const rank of new Set(scope.ranks ?? []))
    for (const prefix of PER_JOB_KEYS) keys.push([prefix, rank]);
  if (scope.batchId != null) keys.push(["batch", scope.batchId]);
  if (scope.selection) keys.push(["selection-queue"]);
  await Promise.all(keys.map((queryKey) => client.invalidateQueries({ queryKey })));
}
