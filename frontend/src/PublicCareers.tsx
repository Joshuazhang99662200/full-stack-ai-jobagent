import type { Fields, Snapshot } from "./contracts";

const object = (value: unknown): Fields =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Fields)
    : {};
const wording = (value: unknown, fallback: string) =>
  typeof value === "string" && value.trim() ? value : fallback;
const amount = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? String(value)
    : "未记录";
function originalUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function PublicCareers({
  value,
}: {
  value: Snapshot["public_careers"];
}) {
  const state = value?.status ?? "missing";
  const latest = value?.runs.at(-1);
  const completeRun = latest?.status === "complete";
  return (
    <section className="public-careers">
      <h2>公开职位补充</h2>
      <p>
        企业官网与公开招聘接口的补充岗位，地区条件仍需结合完整职位说明核对。
      </p>
      {state === "missing" ? (
        <p role="status">公开职位补充尚未接入。</p>
      ) : state === "invalid" ? (
        <p role="alert">补充渠道的数据暂时无法读取，请核对来源记录。</p>
      ) : (
        <>
          {!latest ? (
            <p role="status">尚未记录公开职位读取，本页不能确认有无岗位。</p>
          ) : !completeRun ? (
            <p role="status">本轮读取尚未完成，已保存的岗位可继续查看。</p>
          ) : !value?.records.length ? (
            <p role="status">本次已完成读取，没有符合条件的补充岗位。</p>
          ) : null}
          {latest && (
            <details>
              <summary>查看本轮覆盖情况</summary>
              <dl className="fields">
                <div>
                  <dt>来源返回</dt>
                  <dd>{amount(latest.raw_returned)} 条</dd>
                </div>
                <div>
                  <dt>本轮取用</dt>
                  <dd>{amount(latest.taken)} 条</dd>
                </div>
                <div>
                  <dt>实际请求</dt>
                  <dd>{amount(latest.http_attempts)} 次</dd>
                </div>
              </dl>
              {latest.resume_board ? (
                <p>部分来源尚未处理完，恢复位置已记录。</p>
              ) : null}
            </details>
          )}
          <div className="public-careers-list">
            {value?.records.map((record) => {
              const listing = object(record.listing);
              const observation = object(record.observation);
              const url = originalUrl(listing.url);
              return (
                <article
                  className="public-career"
                  key={`${record.provider}:${record.board}:${record.source_job_id}`}
                >
                  <h3>{wording(listing.title, "岗位名称未记录")}</h3>
                  <p>
                    {wording(listing.company, "公司未记录")} ·{" "}
                    {wording(listing.location, "地区未标注")}
                  </p>
                  <p>
                    {record.provider === "greenhouse"
                      ? "Greenhouse"
                      : record.provider === "ashby"
                        ? "Ashby"
                        : "来源待核对"}
                  </p>
                  {record.region_decision === "review" && (
                    <span className="public-region">地区条件待核对</span>
                  )}
                  {url && (
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      查看原始岗位
                    </a>
                  )}
                  {typeof observation.jd_raw === "string" &&
                  observation.jd_raw.trim() ? (
                    <details>
                      <summary>
                        {observation.completeness === "full"
                          ? "查看完整职位说明"
                          : "查看已取得的职位文本"}
                      </summary>
                      <p className="public-jd">{observation.jd_raw}</p>
                    </details>
                  ) : (
                    <p>完整职位说明尚未取得。</p>
                  )}
                </article>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
