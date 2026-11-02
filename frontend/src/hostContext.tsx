import { createContext, useContext, useEffect, useState } from "react";
import type { ConsoleDataSource } from "./dataSource";
import type { HostReceipt, HostState } from "./hostContracts";

export interface HostController {
  source: ConsoleDataSource;
  state: HostState;
  refresh(): Promise<void>;
}
export const HostContext = createContext<HostController | null>(null);
export const useHost = () => useContext(HostContext);

/** Write-ahead UI journal: unknown outcomes can only be queried, including after reload. */
export function useHostOperation(scope: string) {
  const host = useHost();
  const key = `ja-console.pending.v1.${host?.source.mode}.${host?.state.candidate_id}.${scope}`;
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    try {
      const existing = localStorage.getItem(key);
      setPending(existing);
      setMessage(existing ? "有一项保存结果未确认，请先核验。" : "");
    } catch {
      setMessage("无法读取操作记录，暂不能保存决定。");
      setPending("unavailable");
    }
  }, [key]);
  async function finish(result: HostReceipt) {
    setMessage(result.message);
    if (result.status !== "unknown") {
      localStorage.removeItem(key);
      setPending(null);
    }
    if (host) await host.refresh();
  }
  async function run(
    task: (operationKey: string) => Promise<HostReceipt>,
    explicitKey?: string,
  ) {
    if (busy || pending) return;
    const operationKey = explicitKey ?? crypto.randomUUID();
    try {
      localStorage.setItem(key, operationKey);
      setPending(operationKey);
    } catch {
      setMessage("操作记录无法保存，尚未提交决定，请在对话中告知。");
      return;
    }
    setBusy(true);
    try {
      await finish(await task(operationKey));
    } catch {
      setMessage("保存结果未确认，请先核验，不要重复操作。");
    } finally {
      setBusy(false);
    }
  }
  async function verify() {
    if (!pending || !host?.source.getOperation || busy) return;
    setBusy(true);
    try {
      await finish(await host.source.getOperation(pending));
    } catch {
      setMessage("仍无法核验保存结果，请保留当前记录并在对话中告知。");
    } finally {
      setBusy(false);
    }
  }
  return { run, verify, busy, pending, message };
}
