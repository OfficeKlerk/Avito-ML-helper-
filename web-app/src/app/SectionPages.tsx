import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { ApiError, call, type Api, type Schemas } from "../shared/api/client";
import { ActionCard } from "../shared/ui/ActionCard";
import { ErrorMessage, Loading, Status } from "../shared/ui/controls";
import { useSession } from "./session";

type Load<T> = (api: Api, signal: AbortSignal) => Promise<T>;
type State<T> = { data: T } | { error: string } | null;

function SectionData<T>({ load, children }: { load: Load<T>; children: (data: T) => ReactNode }) {
  const { api } = useSession();
  const [state, setState] = useState<State<T>>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(api, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setState({ data }); },
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ error: error instanceof ApiError ? error.message : "Не удалось загрузить данные." });
      },
    );
    return () => controller.abort();
  }, [api, load, attempt]);

  if (!state) return <Loading />;
  if ("error" in state) return <ErrorMessage onRetry={() => { setState(null); setAttempt((n) => n + 1); }}>{state.error}</ErrorMessage>;
  return <>{children(state.data)}</>;
}

function Page({ title, children }: { title: string; children: ReactNode }) {
  return <section className="page-stack"><h1>{title}</h1>{children}</section>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="panel empty-state"><p>{children}</p></div>;
}

const loadChat: Load<Schemas["ChatMessageList"]> = (api, signal) => call(api.GET("/api/chat/messages", { signal }));
const loadPlan: Load<Schemas["Onboarding"]> = (api, signal) => call(api.GET("/api/onboarding", { signal }));
const loadActions: Load<Schemas["ActionCardList"]> = (api, signal) => call(api.GET("/api/actions", { signal }));
const loadNotifications: Load<Schemas["NotificationList"]> = (api, signal) => call(api.GET("/api/notifications", { signal }));

export function ChatPage() {
  return <Page title="Чат"><SectionData load={loadChat}>{({ messages }) =>
    messages.length ? <ol className="plain-list message-list">{messages.map((message) =>
      <li key={message.id} className={`panel message message--${message.role}`}>
        <div className="card-heading">
          <strong>{message.role === "user" ? "Вы" : "AI-buddy"}</strong>
          {message.status !== "ok" && <Status tone={message.status === "error" ? "danger" : "warning"}>
            {message.status === "error" ? "Ошибка" : "Упрощённый ответ"}
          </Status>}
        </div>
        <p className="message-text">{message.text}</p>
      </li>)}</ol> : <Empty>История пока пуста.</Empty>
  }</SectionData></Page>;
}

const taskStatus: Record<Schemas["Task"]["status"], string> = {
  todo: "К выполнению", in_progress: "В работе", done: "Выполнено", blocked: "Заблокировано",
};

export function OnboardingPage() {
  const { taskId } = useParams();
  return <Page title="Адаптация"><SectionData load={loadPlan}>{(plan) => {
    if (taskId) {
      const task = plan.stages.flatMap((stage) => stage.tasks).find((item) => item.id === taskId);
      return <div className="panel content-panel">
        <Link to="/onboarding">Все задачи</Link>
        {task ? <><h2>{task.title}</h2><p>{task.description}</p><Status>{taskStatus[task.status]}</Status>
          {task.related_action_id && <p><Link to={`/actions/${encodeURIComponent(task.related_action_id)}`}>Связанная заявка</Link></p>}</>
          : <p role="status">Задача не найдена.</p>}
      </div>;
    }
    if (!plan.stages.length) return <Empty>Плана адаптации пока нет.</Empty>;
    return <>
      <div className="panel content-panel">
        <div className="card-heading"><h2>Прогресс</h2><strong>{plan.progress}%</strong></div>
        <progress aria-label="Прогресс адаптации" max={100} value={plan.progress} />
      </div>
      {plan.stages.map((stage) => <section key={stage.id} className="panel content-panel">
        <h2>{stage.title}</h2>
        <ul className="plain-list row-list">{stage.tasks.map((task) => <li key={task.id}>
          <Link to={`/onboarding/tasks/${encodeURIComponent(task.id)}`}>{task.title}</Link>
          <Status>{taskStatus[task.status]}</Status>
        </li>)}</ul>
      </section>)}
    </>;
  }}</SectionData></Page>;
}

export function ActionsPage() {
  return <Page title="Заявки"><SectionData load={loadActions}>{({ actions }) =>
    actions.length ? <ul className="plain-list card-list">{actions.map((action) => <li key={action.id}>
      <ActionCard action={action} footer={<Link to={`/actions/${encodeURIComponent(action.id)}`}
        aria-label={`Открыть заявку «${action.title}»`}>Открыть заявку</Link>} />
    </li>)}</ul> : <Empty>Заявок пока нет.</Empty>
  }</SectionData></Page>;
}

export function ActionPage() {
  const { actionId = "" } = useParams();
  return <Page title="Заявка">
    <Link to="/actions">Все заявки</Link>
    <ActionDetail key={actionId} id={actionId} />
  </Page>;
}

function ActionDetail({ id }: { id: string }) {
  // ActionPage remounts the detail when a different identifier is selected.
  const load = useCallback<Load<Schemas["ActionCard"]>>((api, signal) =>
    call(api.GET("/api/actions/{action_id}", { signal, params: { path: { action_id: id } } })), [id]);
  return <SectionData load={load}>{(action) => <ActionCard action={action} />}</SectionData>;
}

export function NotificationsPage() {
  const { notificationId } = useParams();
  return <Page title="Уведомления"><SectionData load={loadNotifications}>{({ items }) => {
    const visible = notificationId ? items.filter((item) => item.id === notificationId) : items;
    return <>
      {notificationId && <Link to="/notifications">Все уведомления</Link>}
      {visible.length ? <ul className="plain-list card-list">{visible.map((item) => <li className="panel content-panel" key={item.id}>
        <div className="card-heading"><h2>{item.kind === "reminder" ? "Напоминание" : "Статус заявки"}</h2>
          <Status tone={item.read ? "neutral" : "active"}>{item.read ? "Прочитано" : "Новое"}</Status></div>
        <p>{item.text}</p>
        <div className="button-row">
          {!notificationId && <Link to={`/notifications/${encodeURIComponent(item.id)}`}
            aria-label={`Открыть уведомление «${item.text}»`}>Открыть</Link>}
          {item.task_id && <Link to={`/onboarding/tasks/${encodeURIComponent(item.task_id)}`}>К задаче</Link>}
          {item.action_id && <Link to={`/actions/${encodeURIComponent(item.action_id)}`}>К заявке</Link>}
        </div>
      </li>)}</ul> : <Empty>{notificationId ? "Уведомление не найдено." : "Уведомлений пока нет."}</Empty>}
    </>;
  }}</SectionData></Page>;
}
