import { label, type Report } from "./agentReport";

/** A guide to recorded host work, never an approval or delivery authority. */
export function JobWorkflow({
  item,
  greetings,
}: {
  item: Report;
  greetings: boolean;
}) {
  const steps = [
    "fetch",
    "detail",
    "match",
    ...(greetings ? ["draft_greeting"] : []),
    "review",
    "approval",
    "readback",
    "report",
  ];
  const ended = item.lane === "closed";
  return (
    <section className="jq-workflow" aria-labelledby="job-workflow-title">
      <header>
        <h3 id="job-workflow-title">工作流程</h3>
        <p className="note">蓝色：已完成　灰色：未开始或未记录　描边：现在</p>
      </header>
      <p>{item.milestone}</p>
      <ol>
        {steps.map((step, index) => {
          const work = item.stages.filter(
            (stage) => stage.event.activity === step,
          );
          // Concurrent attempts remain visible; an older completion cannot hide open work.
          const state =
            [
              "started",
              "heartbeat",
              "waiting",
              "unconfirmed",
              "failed",
              "completed",
            ].find((status) => work.some((stage) => stage.status === status)) ??
            "missing";
          const now =
            !ended && ["started", "heartbeat", "waiting"].includes(state);
          const status = state === "missing" ? "未记录" : label(state);
          return (
            <li
              key={step}
              data-step={step}
              data-work-state={state}
              aria-current={now ? "step" : undefined}
            >
              <span className="jq-workflow-dot" aria-hidden="true">
                {state === "completed" ? "✓" : index + 1}
              </span>
              <div>
                <strong>{label(step)}</strong>
                <small>
                  {now
                    ? "现在 · "
                    : ended && state !== "missing" && state !== "completed"
                      ? "结束前记录 · "
                      : ""}
                  {status}
                </small>
                {state !== "completed" &&
                  work.some((stage) => stage.status === "completed") && (
                    <small>另有已完成记录</small>
                  )}
              </div>
            </li>
          );
        })}
        {item.next && !ended && (
          <li data-step="next" data-work-state="planned">
            <span className="jq-workflow-dot" aria-hidden="true">
              →
            </span>
            <div>
              <strong>下一步</strong>
              <small>计划 · {item.next}</small>
            </div>
          </li>
        )}
      </ol>
      <p className="note">
        按已保存的工作记录标记，可并行或跳过步骤；“未记录”不代表尚未开始。准备审批完成不代表本人已批准，工作完成也不代表已投递。
      </p>
    </section>
  );
}
