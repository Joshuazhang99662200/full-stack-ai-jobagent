import type { HostTodo } from "./hostContracts";
import { useHost, useHostOperation } from "./hostContext";
import { currentMaterial } from "./hostService";

function Todo({ todo }: { todo: HostTodo }) {
  const host = useHost(),
    operation = useHostOperation(todo.contact_id);
  const entry = host?.state.jobs.find(
    (j) => j.contact_id === todo.contact_id && j.job_id === todo.job_id,
  );
  const material = entry && currentMaterial(entry);
  const stale = material?.revision !== todo.material_revision;
  return (
    <article className="host-todo">
      <h4>{todo.question}</h4>
      {stale && (
        <p className="notice">材料已变化，请重新审阅新版；该事项仍待处理。</p>
      )}
      <h5>判断依据</h5>
      <ul>
        {todo.basis.map((basis, i) => (
          <li key={i}>{basis}</li>
        ))}
      </ul>
      <h5>你的选择</h5>
      {todo.options.map((option) => (
        <div key={option.option_id}>
          <button
            disabled={
              !host?.source.recordDecision ||
              !material ||
              stale ||
              operation.busy ||
              !!operation.pending ||
              todo.status === "resolved"
            }
            onClick={() =>
              void operation.run((key) =>
                host!.source.recordDecision!({
                  candidate_id: host!.state.candidate_id,
                  job_id: todo.job_id,
                  contact_id: todo.contact_id,
                  operation_key: key,
                  kind: "answer_todo",
                  material_revision: todo.material_revision,
                  body: material!.body,
                  attachment_digests: material!.attachments.map(
                    (a) => a.digest,
                  ),
                  note: option.label,
                  todo_id: todo.todo_id,
                  option_id: option.option_id,
                }),
              )
            }
          >
            {option.label}
          </button>
          <p>{option.consequence}</p>
        </div>
      ))}
      {todo.result && <p>处理结果：{todo.result}</p>}
      {operation.message && <p role="status">{operation.message}</p>}
      {operation.pending && (
        <button
          disabled={operation.busy || !host?.source.getOperation}
          onClick={() => void operation.verify()}
        >
          核验保存结果
        </button>
      )}
    </article>
  );
}
export function TodoPanel({ contactId }: { contactId: string }) {
  const host = useHost();
  const todos =
    host?.state.todos.filter(
      (t) =>
        t.contact_id === contactId &&
        t.requires_person &&
        t.host_resolved &&
        t.basis.length &&
        t.options.length,
    ) ?? [];
  return (
    <section>
      <h3>需要你决定</h3>
      {todos.length ? (
        todos.map((todo) => <Todo key={todo.todo_id} todo={todo} />)
      ) : (
        <p>
          {host?.source.mode !== "snapshot" && host
            ? "当前核对范围内没有需要你决定的事项。"
            : "个人待办来源尚未接入，无法确认是否有待办。"}
        </p>
      )}
    </section>
  );
}
