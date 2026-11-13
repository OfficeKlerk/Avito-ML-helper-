import { useCallback, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { call, type Schemas } from "../shared/api/client";
import { useApiData, type Load } from "../shared/api/useApiData";
import { ActionCard } from "../shared/ui/ActionCard";
import { ErrorMessage, Loading, Status } from "../shared/ui/controls";
import { useSession } from "./session";

function SectionData<T>({ load, children }: { load: Load<T>; children: (data: T) => ReactNode }) {
  const { api } = useSession();
  const { state, reload } = useApiData(api, load);
  if (state.status === "loading") return <Loading />;
  if (state.status === "error") return <ErrorMessage onRetry={reload}>{state.message}</ErrorMessage>;
  return <>{children(state.data)}</>;
}

function Page({ title, children }: { title: string; children: ReactNode }) {
  return <section className="page-stack"><h1>{title}</h1>{children}</section>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="panel empty-state"><p>{children}</p></div>;
}

const loadChat: Load<Schemas["ChatMessageList"]> = (api, signal) => call(api.GET("/api/chat/messages", { signal }));
const loadActions: Load<Schemas["ActionCardList"]> = (api, signal) => call(api.GET("/api/actions", { signal }));

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
