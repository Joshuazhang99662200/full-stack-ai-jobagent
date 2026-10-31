import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Console } from "./Console";
import type { Definitions, Snapshot } from "./contracts";
import { demo } from "./demo";
import demoDefinitions from "./demo-definitions.json";
import "./app.css";
function App() {
  const example = new URLSearchParams(location.search).get("demo") === "1";
  const [data, setData] = useState<Snapshot | null>(example ? demo : null);
  const [definitions, setDefinitions] = useState<Definitions>(
    example ? demoDefinitions : {},
  );
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!example);
  const controller = useRef<AbortController | null>(null);
  async function load() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError("");
    try {
      const values = await Promise.all(
        ["/api/snapshot", "/api/definitions"].map(async (path) => {
          const response = await fetch(path, {
            cache: "no-store",
            signal: request.signal,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.json();
        }),
      );
      if (
        values[0].schema_version !== "1.0" ||
        !Array.isArray(values[0].runs) ||
        !Array.isArray(values[0].jobs) ||
        !Array.isArray(values[0].sources)
      )
        throw new Error("契约版本或形状不兼容");
      if (request.signal.aborted) return;
      setData(values[0]);
      setDefinitions(values[1]);
    } catch (reason) {
      if (request.signal.aborted) return;
      setData(null);
      setError(reason instanceof Error ? reason.message : "未知错误");
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    if (!example) void load();
    return () => controller.current?.abort();
  }, []);
  if (error)
    return (
      <main className="load-state">
        <h1>岗位任务队列</h1>
        <p role="alert">读取失败：{error}。请检查本地查询服务与候选人配置。</p>
        <button onClick={() => void load()}>重新读取</button>
      </main>
    );
  if (!data)
    return (
      <main className="load-state">
        <h1>岗位任务队列</h1>
        <p role="status">正在读取本地任务记录…</p>
        <div className="skeleton" aria-hidden="true" />
      </main>
    );
  return (
    <Console
      syncUrl
      snapshot={data}
      definitions={definitions}
      demo={example}
      onRefresh={example ? undefined : () => void load()}
      refreshing={loading}
    />
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
