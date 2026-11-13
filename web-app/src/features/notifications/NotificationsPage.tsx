import { useState } from "react";
import { Link, useParams } from "react-router";
import { useSession } from "../../app/session";
import { ApiError, call, type Schemas } from "../../shared/api/client";
import { useApiData, type Load } from "../../shared/api/useApiData";
import { Button, ErrorMessage, Loading, Status } from "../../shared/ui/controls";

type Notification = Schemas["Notification"];

const loadNotifications: Load<Schemas["NotificationList"]> = (api, signal) => call(api.GET("/api/notifications", { signal }));
const when = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });

/** O4: напоминания и смены статусов заявок. Прочтение сохраняет core-api, после перезагрузки оно на месте. */
export function NotificationsPage() {
  const { notificationId } = useParams();
  const { api } = useSession();
  const { state, reload, replace } = useApiData(api, loadNotifications);

  let content;
  if (state.status === "loading") content = <Loading />;
  else if (state.status === "error") content = <ErrorMessage onRetry={reload}>{state.message}</ErrorMessage>;
  else {
    // Один id — одна строка, даже если сервер или повтор вернули запись дважды.
    const items = [...new Map(state.data.items.map((item) => [item.id, item])).values()];
    const visible = notificationId ? items.filter((item) => item.id === notificationId) : items;
    const markRead = (updated: Notification) => replace({ items: items.map((item) => item.id === updated.id ? updated : item) });
    content = <>
      {notificationId && <Link to="/notifications">Все уведомления</Link>}
      {visible.length ? <ul className="plain-list card-list">{visible.map((item) =>
        <NotificationItem key={item.id} item={item} single={Boolean(notificationId)} onRead={markRead} />)}</ul>
        : <div className="panel empty-state"><p>{notificationId ? "Уведомление не найдено." : "Уведомлений пока нет."}</p></div>}
    </>;
  }
  return <section className="page-stack"><h1>Уведомления</h1>{content}</section>;
}

function NotificationItem({ item, single, onRead }: { item: Notification; single: boolean; onRead: (item: Notification) => void }) {
  const { api } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function markRead() {
    setBusy(true);
    setError(null);
    try {
      onRead(await call(api.PATCH("/api/notifications/{notification_id}", {
        params: { path: { notification_id: item.id } }, body: { read: true },
      })));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось отметить уведомление. Попробуй ещё раз.");
    } finally {
      setBusy(false);
    }
  }
  return <li className={`panel content-panel${item.read ? "" : " notification--unread"}`}>
    <div className="card-heading">
      <div><h2>{item.kind === "reminder" ? "Напоминание" : "Статус заявки"}</h2>
        <p className="muted"><time dateTime={item.created_at}>{when.format(new Date(item.created_at))}</time></p></div>
      <Status tone={item.read ? "neutral" : "active"}>{item.read ? "Прочитано" : "Новое"}</Status>
    </div>
    <p>{item.text}</p>
    <div className="button-row">
      {!single && <Link to={`/notifications/${encodeURIComponent(item.id)}`} aria-label={`Открыть уведомление «${item.text}»`}>Открыть</Link>}
      {item.task_id && <Link to={`/onboarding/tasks/${encodeURIComponent(item.task_id)}`}>К задаче</Link>}
      {item.action_id && <Link to={`/actions/${encodeURIComponent(item.action_id)}`}>К заявке</Link>}
      {!item.read && <Button tone="secondary" busy={busy} busyLabel="Отмечаем…" onClick={markRead}>Отметить прочитанным</Button>}
    </div>
    {error && <ErrorMessage>{error}</ErrorMessage>}
  </li>;
}
