import { createContext, useContext } from "react";
import type { MuseActions } from "./contracts";

export interface MuseConfiguration {
  refreshMs?: number;
  batchRefreshMs?: number;
  progressBatchLimit?: number;
  executionSummary?: string;
  readonlyReason?: string;
  disabledDecisions?: Partial<Record<string, string>>;
}
export type MuseCvFiles = Record<number, { v1?: string; v2?: string }>;
export const MuseContext = createContext<{
  actions: MuseActions;
  configuration: MuseConfiguration;
  cvFiles: MuseCvFiles;
} | null>(null);
export function useMuseActions() {
  const context = useContext(MuseContext);
  if (!context) throw new Error("Muse actions are not connected");
  return context.actions;
}
export const useMuseConfiguration = () =>
  useContext(MuseContext)?.configuration ?? {};
export const useMuseCvFiles = () => useContext(MuseContext)?.cvFiles ?? {};
