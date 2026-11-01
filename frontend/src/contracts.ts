/** Transport view only. Domain fields are supplied by Python JSON Schema, never redefined here. */
export type Fields = Record<string, unknown>;
export interface Activity extends Fields {
  event_id: string;
  activity_id: string;
  activity: string;
  status: string;
  occurred_at: string;
  owner: string;
  next_step?: string | null;
}
export interface RunView {
  run: Fields;
  activities: Activity[];
  freshness: string;
}
export interface JobView {
  match_result?: Fields | null;
  match_context?: Fields | null;
  hard_filter_result?: Fields | null;
  hard_filter_context?: Fields | null;
  job: Fields;
  meta: Fields;
  history: Fields[];
}
export interface Snapshot {
  schema_version: "1.0";
  candidate_id: string;
  generated_at: string;
  sources: { name: string; status: string; message: string | null }[];
  jobs: JobView[];
  runs: RunView[];
  approvals: Fields[];
}
export type Definitions = Record<string, unknown>;
export const text = (value: unknown) =>
  value == null
    ? "未记录"
    : typeof value === "string"
      ? value
      : JSON.stringify(value);
