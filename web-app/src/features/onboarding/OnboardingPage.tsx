import { useState } from "react";
import { Link, useParams } from "react-router";
import { useSession } from "../../app/session";
import { ApiError, call, type Schemas } from "../../shared/api/client";
import { useApiData, type Load } from "../../shared/api/useApiData";
import { Button, ErrorMessage, Loading, Status } from "../../shared/ui/controls";
import { describeDue } from "./dates";
import { adaptationRefreshInterval, taskContext, taskPath } from "./taskLinks";

type Task = Schemas["Task"];
type TaskStatus = Task["status"];

const loadPlan: Load<Schemas["Onboarding"]> = (api, signal) =>
  call(api.GET("/api/onboarding", { signal, cache: "no-store" }));

const TASK_STATUS: Record<TaskStatus, [string, "neutral" | "active" | "success" | "danger"]> = {
  todo: ["К выполнению", "neutral"], in_progress: ["В работе", "active"], done: ["Выполнено", "success"], blocked: ["Заблокировано", "danger"],
};
const STAGE_STATUS: Record<Schemas["Stage"]["status"], string> = { todo: "Впереди", in_progress: "Сейчас", done: "Пройден" };
// Кнопки смены статуса: куда можно перевести задачу и как это назвать.
const MOVES: [TaskStatus, string][] = [["in_progress", "Взять в работу"], ["done", "Отметить выполненной"], ["blocked", "Есть препятствие"], ["todo", "Вернуть в план"]];

/** O1, O2: план адаптации текущего пользователя. Приоритеты и прогресс считает core-api, клиент только показывает. */
export function OnboardingPage() {
  const { taskId } = useParams();
  const { api } = useSession();
  const { state, reload, replace } = useApiData(api, loadPlan, adaptationRefreshInterval);

  function updateTask(updated: Task) {
    replace((plan) => ({
      ...plan,
      stages: plan.stages.map((stage) => ({
        ...stage,
        tasks: stage.tasks.map((task) => task.id === updated.id ? updated : task),
      })),
    }));
    reload();
  }

  let content;
  if (state.status === "loading") content = <Loading />;
  else if (state.status === "error") content = <ErrorMessage onRetry={reload}>{state.message}</ErrorMessage>;
  else if (taskId) content = <TaskDetail plan={state.data} taskId={taskId} onChanged={updateTask} />;
  else content = <Plan plan={state.data} />;
  return <section className="page-stack"><h1>Адаптация</h1>
    {state.status === "ready" && state.refreshError &&
      <ErrorMessage onRetry={reload}>Не удалось обновить план. {state.refreshError}</ErrorMessage>}
    {content}
  </section>;
}

function Plan({ plan }: { plan: Schemas["Onboarding"] }) {
  if (!plan.stages.some((stage) => stage.tasks.length)) return <div className="panel empty-state"><p>Плана адаптации пока нет. Если это ошибка, напиши наставнику.</p></div>;
  const allDone = plan.stages.every((stage) => stage.tasks.every((task) => task.status === "done"));
  return <>
    <div className="panel content-panel">
      <div className="card-heading"><h2>Прогресс</h2><strong>{plan.progress}%</strong></div>
      <progress aria-label="Прогресс адаптации" max={100} value={plan.progress} />
    </div>
    <section className="panel content-panel" aria-labelledby="next-steps">
      <h2 id="next-steps">Что сделать дальше</h2>
      {plan.next_steps.length ? <ol className="next-steps">{plan.next_steps.map((step) => <li key={step.task_id}>
        <Link to={taskPath(step.task_id)}>{step.title}</Link>
        <p className="muted">{step.reason}</p>
      </li>)}</ol> : <p className="muted">{allDone ? "Все задачи выполнены." : "Срочных шагов нет."}</p>}
    </section>
    {plan.stages.map((stage) => <section key={stage.id} className="panel content-panel" aria-labelledby={`stage-${stage.id}`}>
      <div className="card-heading">
        <div><h2 id={`stage-${stage.id}`}>{stage.title}</h2><p className="muted">{stage.period}</p></div>
        <Status tone={stage.status === "in_progress" ? "active" : stage.status === "done" ? "success" : "neutral"}>{STAGE_STATUS[stage.status]}</Status>
      </div>
      <ul className="plain-list row-list">{stage.tasks.map((task) => <li key={task.id}>
        <Link to={taskPath(task.id)}>{task.title}</Link>
        <TaskBadges task={task} />
      </li>)}</ul>
    </section>)}
  </>;
}

function TaskBadges({ task }: { task: Task }) {
  const [label, tone] = TASK_STATUS[task.status];
  const due = describeDue(task.due_date, task.status === "done");
  return <span className="button-row">
    {due && <Status tone={due.tone}>{due.label}</Status>}
    <Status tone={tone}>{label}</Status>
  </span>;
}

function TaskDetail({ plan, taskId, onChanged }: { plan: Schemas["Onboarding"]; taskId: string; onChanged: (task: Task) => void }) {
  const task = plan.stages.flatMap((stage) => stage.tasks).find((item) => item.id === taskId);
  return <div className="panel content-panel">
    <Link to="/onboarding">Все задачи</Link>
    {task ? <>
      <div className="card-heading"><h2>{task.title}</h2><TaskBadges task={task} /></div>
      {task.description && <p>{task.description}</p>}
      {task.links.length > 0 && <ul className="plain-list">{task.links.map((link) => <li key={link.url}><SafeLink {...link} /></li>)}</ul>}
      <div className="button-row">
        {task.related_action_id && <Link to={`/actions/${encodeURIComponent(task.related_action_id)}${taskContext(task.id)}`}>Связанная заявка</Link>}
        <Link to={`/chat${taskContext(task.id)}`}
          state={{ question: `Помоги с задачей «${task.title}». Что нужно сделать?` }}>Спросить в чате</Link>
      </div>
      {/* key: после обновления плана сбрасываем ошибку прошлой попытки */}
      <StatusControl key={`${task.id}:${task.status}`} task={task} onChanged={onChanged} />
    </> : <p role="status">Задача не найдена.</p>}
  </div>;
}

/** Ссылка из плана: открываем только http(s). kb:// — документ базы знаний, прочие схемы (javascript: и т. п.) не открываем. */
export function SafeLink({ title, url }: Schemas["Link"]) {
  if (/^https?:\/\//i.test(url)) return <a href={url} target="_blank" rel="noreferrer">{title}</a>;
  return <span>{title}{url.startsWith("kb://") ? " — документ базы знаний" : ""}</span>;
}

function StatusControl({ task, onChanged }: { task: Task; onChanged: (task: Task) => void }) {
  const { api } = useSession();
  const [pending, setPending] = useState<TaskStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function move(status: TaskStatus) {
    setPending(status);
    setError(null);
    try {
      const updated = await call(api.PATCH("/api/onboarding/tasks/{task_id}", {
        params: { path: { task_id: task.id } }, body: { status },
      }));
      onChanged(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось изменить статус. Попробуй ещё раз.");
    } finally {
      setPending(null);
    }
  }
  return <div className="content-panel">
    {task.related_action_type === "access_request" && task.status !== "done" &&
      <p className="muted">Задача завершится, когда доступ выдадут. Отметить её выполненной раньше не получится.</p>}
    <div className="button-row">{MOVES.filter(([status]) => status !== task.status).map(([status, label]) =>
      <Button key={status} tone={status === "done" ? "primary" : "secondary"} busy={pending === status} busyLabel="Сохраняем…"
        disabled={pending !== null} onClick={() => move(status)}>{label}</Button>)}
    </div>
    {error && <ErrorMessage>{error}</ErrorMessage>}
  </div>;
}
