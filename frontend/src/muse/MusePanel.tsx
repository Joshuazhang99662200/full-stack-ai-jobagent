import { useEffect, useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ConsoleDataSource } from "../dataSource";
import type { MuseActions } from "./contracts";
import {
  MuseContext,
  type MuseConfiguration,
  type MuseCvFiles,
} from "./context";
import { MuseApp } from "./MuseApp";
import { MuseCurrentApp } from "./MuseCurrentApp";
import { createMuseActions } from "./adapter";
import "./theme.css";

export interface MusePanelProps {
  actions: MuseActions;
  appearance?: "current" | "zip";
  configuration?: MuseConfiguration;
  cvFiles?: MuseCvFiles;
}
/** Source-derived Muse UI; the host supplies its own RPC implementation and assets. */
export function MusePanel({
  actions,
  appearance = "current",
  configuration = {},
  cvFiles = {},
}: MusePanelProps) {
  const client = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
    [actions],
  );
  useEffect(() => () => client.clear(), [client]);
  return (
    <QueryClientProvider client={client}>
      <MuseContext.Provider value={{ actions, configuration, cvFiles }}>
        <div className="hatch-space-root" data-hatch-space-root>
          {appearance === "zip" ? <MuseApp /> : <MuseCurrentApp />}
        </div>
      </MuseContext.Provider>
    </QueryClientProvider>
  );
}
export function MuseSourcePanel({
  source,
  ...props
}: { source: ConsoleDataSource } & Omit<MusePanelProps, "actions">) {
  const actions = useMemo(
    () =>
      createMuseActions(source, {
        operationStore: {
          load: (key) =>
            typeof localStorage === "undefined"
              ? null
              : localStorage.getItem(key),
          save: (key, value) => {
            if (typeof localStorage === "undefined")
              throw new Error("写入记录未接入");
            localStorage.setItem(key, value);
          },
        },
      }),
    [source],
  );
  return (
    <div data-template="muse-source">
      {source.mode === "demo" && (
        <div
          role="status"
          className="bg-[var(--surface)] px-4 py-1 text-xs text-[var(--dim)]"
        >
          合成演示 · 不访问真实招聘渠道
        </div>
      )}
      <MusePanel
        actions={actions}
        {...props}
        configuration={{
          ...props.configuration,
          ...(!source.recordDecision
            ? { readonlyReason: "决定保存服务尚未接入，当前只能查看已有记录。" }
            : {}),
          disabledDecisions: {
            resolve_block: "屏蔽及重复岗位的处理服务尚未接入",
            ...props.configuration?.disabledDecisions,
          },
        }}
      />
    </div>
  );
}
