import type { HostMaterial } from "./hostContracts";
import { safeMaterialUrl } from "./hostService";

export function MaterialView({ material }: { material: HostMaterial }) {
  return (
    <section className="host-material">
      <h4>{material.label}</h4>
      {material.body && <p className="jq-exact">{material.body}</p>}
      {material.attachments.length ? (
        <ul>
          {material.attachments.map((a) => {
            const url = a.digest.trim() ? safeMaterialUrl(a.url) : null;
            return (
              <li key={a.digest || a.name}>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer">
                    打开 {a.name}
                  </a>
                ) : (
                  `${a.name}：实际文件来源尚未接入`
                )}
                <span className="host-material-version">
                  {" "}
                  · 材料版本：{material.label}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="note">本份材料未附文件。</p>
      )}
    </section>
  );
}
