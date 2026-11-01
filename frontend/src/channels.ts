import type { JobView } from "./contracts";
import type { Report } from "./agentReport";

/** Presentation routes only; a visible route never grants an execution capability. */
export function channelOf(job: JobView) {
  const value = String(job.job.platform ?? job.job.source ?? "").toLowerCase();
  if (["boss", "boss直聘", "boss直聘招聘"].includes(value))
    return { name: "BOSS", greetings: true, known: true };
  if (["zhaopin", "智联", "智联招聘"].includes(value))
    return { name: "智联", greetings: true, known: true };
  if (["liepin", "猎聘"].includes(value))
    return { name: "猎聘", greetings: false, known: true };
  return { name: value || "渠道未记录", greetings: false, known: false };
}

export function routedReport(job: JobView, item: Report): Report {
  if (channelOf(job).greetings) return item;
  return {
    ...item,
    milestone: ["greeting_sent", "greeting_read"].includes(
      String(job.job.pipeline_state),
    )
      ? "历史沟通状态需按渠道核对"
      : job.job.pipeline_state === "draft_pending"
        ? "投递材料待准备"
        : item.milestone,
    next: item.next?.includes("招呼") ? null : item.next,
  };
}
