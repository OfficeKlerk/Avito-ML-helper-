import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { useSession } from "../../app/session";
import { call, type Schemas } from "../../shared/api/client";
import { useApiData, type Load } from "../../shared/api/useApiData";
import { ErrorMessage, Loading } from "../../shared/ui/controls";
import { ActionItem } from "./ActionItem";

const loadActions: Load<Schemas["ActionCardList"]> = (api, signal) => call(api.GET("/api/actions", { signal }));

export function ActionsPage() {
  const { api } = useSession();
  const { state, reload, replace } = useApiData(api, loadActions);
  let content;
  if (state.status === "loading") content = <Loading />;
  else if (state.status === "error") content = <ErrorMessage onRetry={reload}>{state.message}</ErrorMessage>;
  else if (!state.data.actions.length) content = <div className="panel empty-state"><p>Заявок пока нет. Их создаёт помощник в чате.</p></div>;
  else {
    const actions = state.data.actions;
    const update = (card: Schemas["ActionCard"]) => replace({ actions: actions.map((item) => item.id === card.id ? card : item) });
    content = <ul className="plain-list card-list">{actions.map((action) => <li key={action.id}>
      <ActionItem action={action} onChange={update} footer={<Link to={`/actions/${encodeURIComponent(action.id)}`}
        aria-label={`Открыть заявку «${action.title}»`}>Открыть заявку</Link>} />
    </li>)}</ul>;
  }
  return <section className="page-stack"><h1>Заявки</h1>{content}</section>;
}

export function ActionPage() {
  const { actionId = "" } = useParams();
  return <section className="page-stack"><h1>Заявка</h1>
    <Link to="/actions">Все заявки</Link>
    <ActionDetail key={actionId} id={actionId} />
  </section>;
}

function ActionDetail({ id }: { id: string }) {
  const { api } = useSession();
  const load = useCallback<Load<Schemas["ActionCard"]>>((api, signal) =>
    call(api.GET("/api/actions/{action_id}", { signal, params: { path: { action_id: id } } })), [id]);
  const { state, reload, replace } = useApiData(api, load);
  if (state.status === "loading") return <Loading />;
  if (state.status === "error") return <ErrorMessage onRetry={reload}>{state.message}</ErrorMessage>;
  return <ActionItem action={state.data} onChange={replace} />;
}
