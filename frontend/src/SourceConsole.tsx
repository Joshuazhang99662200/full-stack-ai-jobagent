import { useCallback, useEffect, useRef, useState } from "react";
import { Console, type ConsoleProps } from "./Console";
import type { ConsoleDataSource } from "./dataSource";
import { checkSnapshot, unavailableHost } from "./dataSource";
import type { Definitions, Snapshot } from "./contracts";
import type { HostState } from "./hostContracts";

export interface SourceConsoleProps extends Omit<
  ConsoleProps,
  "snapshot" | "definitions" | "host" | "demo" | "onRefresh" | "refreshing"
> {
  source: ConsoleDataSource;
}
export function SourceConsole({ source, ...props }: SourceConsoleProps) {
  const [data, setData] = useState<{
    snapshot: Snapshot;
    definitions: Definitions;
    host: HostState;
    source: ConsoleDataSource;
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const active = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    const sequence = ++active.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError("");
    try {
      const [snapshot, definitions, state, todos, channels] = await Promise.all(
        [
          source.getSnapshot(request.signal),
          source.getDefinitions(request.signal),
          source.getHostState(request.signal),
          source.getTodos(),
          source.getChannelLogin(),
        ],
      );
      checkSnapshot(snapshot);
      if (
        source.mode !== "snapshot" &&
        (state.protocol_version !== "1.0" ||
          state.candidate_id !== snapshot.candidate_id ||
          state.jobs.some(
            (j) =>
              !snapshot.jobs.some(
                (s) =>
                  s.job.job_id === j.job_id &&
                  s.job.pipeline_id === j.contact_id,
              ),
          ))
      )
        throw new Error("宿主协议版本或候选人范围不匹配");
      if (sequence !== active.current || request.signal.aborted) return;
      setData({
        source,
        snapshot,
        definitions,
        host:
          source.mode === "snapshot"
            ? unavailableHost(snapshot.candidate_id)
            : { ...state, todos, channels },
      });
    } catch (reason) {
      if (sequence !== active.current || request.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "未知读取错误");
    } finally {
      if (sequence === active.current && !request.signal.aborted)
        setLoading(false);
    }
  }, [source]);
  useEffect(() => {
    setData(null);
    void load();
    return () => {
      ++active.current;
      controller.current?.abort();
    };
  }, [load]);
  if (!data || data.source !== source)
    return (
      <main className="load-state">
        <h1>岗位进展</h1>
        {error ? (
          <>
            <p role="alert">读取失败：{error}。请检查本地服务与数据来源。</p>
            <button onClick={() => void load()}>重新读取</button>
          </>
        ) : (
          <>
            <p role="status">正在读取本地任务记录…</p>
            <div className="skeleton" aria-hidden="true" />
          </>
        )}
      </main>
    );
  return (
    <>
      {error && (
        <p className="notice" role="alert">
          刷新失败：{error}。下面保留的是旧记录，当前状态待核对。
        </p>
      )}
      <Console
        {...props}
        snapshot={data.snapshot}
        definitions={data.definitions}
        demo={source.mode === "demo"}
        onRefresh={() => void load()}
        refreshing={loading}
        host={{ source, state: data.host, refresh: load }}
      />
    </>
  );
}
