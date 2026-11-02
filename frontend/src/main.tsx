import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { SourceConsole } from "./SourceConsole";
import { createHttpSource, type ConsoleDataSource } from "./dataSource";
import { createDemoSource } from "./demoHost";
import "./app.css";

function App() {
  const example = new URLSearchParams(location.search).get("demo") === "1";
  const [source, setSource] = useState<ConsoleDataSource | null>(() =>
    example ? null : createHttpSource(),
  );
  const [error, setError] = useState("");
  useEffect(() => {
    if (!example) return;
    let active = true;
    void Promise.all([import("./demo"), import("./demo-definitions.json")])
      .then(async ([{ demo }, definitions]) => {
        const key = "ja-console.synthetic.v1.CAND_DEMO";
        const next = await createDemoSource({
          snapshot: demo,
          definitions: definitions.default,
          storage: {
            load: () => localStorage.getItem(key),
            save: (value) => localStorage.setItem(key, value),
          },
        });
        if (active) setSource(next);
      })
      .catch(() => {
        if (active)
          setError(
            "合成存储无法读取，请在排查时核对；未自动重置或接入真实数据。",
          );
      });
    return () => {
      active = false;
    };
  }, [example]);
  if (error)
    return (
      <main className="load-state">
        <h1>岗位进展</h1>
        <p role="alert">{error}</p>
      </main>
    );
  if (!source)
    return (
      <main className="load-state">
        <h1>岗位进展</h1>
        <p role="status">正在读取本地任务记录…</p>
      </main>
    );
  return <SourceConsole source={source} syncUrl />;
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
