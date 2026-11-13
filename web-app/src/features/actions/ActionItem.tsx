import { useState, type ReactNode } from "react";
import { useSession } from "../../app/session";
import { ApiError, call, type Schemas } from "../../shared/api/client";
import { ActionCard } from "../../shared/ui/ActionCard";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { Button } from "../../shared/ui/controls";
import { confirmKey, forgetConfirmKey } from "./confirmKey";

type Card = Schemas["ActionCard"];
type Operation = "confirm" | "cancel";

// Те же правила, что в core-api: отправить можно черновик, отменить — черновик или отправленную заявку.
const canConfirm = (card: Card) => card.status === "draft";
const canCancel = (card: Card) => card.status === "draft" || card.status === "submitted";

/**
 * R1–R3: карточка заявки с подтверждением и отменой. Статус всегда берётся с сервера:
 * после ответа, а если ответа нет или он конфликтный — перечитываем карточку.
 * Подходит и для списка заявок, и для ответа в чате.
 */
export function ActionItem({ action, onChange, footer }: { action: Card; onChange: (card: Card) => void; footer?: ReactNode }) {
  const { api, user } = useSession();
  const [dialog, setDialog] = useState<Operation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [notice, setNotice] = useState<string | null>(null);
  const scope = `${user?.id}.${action.id}`;
  const path = { params: { path: { action_id: action.id } } };

  async function reread(): Promise<Card | null> {
    try {
      const card = await call(api.GET("/api/actions/{action_id}", path));
      onChange(card);
      return card;
    } catch {
      return null;
    }
  }

  function close(card: Card | null, message: string | null = null) {
    if (dialog === "confirm" && card && !canConfirm(card)) forgetConfirmKey(scope);
    setDialog(null);
    setError(undefined);
    setNotice(message);
  }

  async function run(operation: Operation) {
    setBusy(true);
    setError(undefined);
    try {
      const card = operation === "confirm"
        ? await call(api.POST("/api/actions/{action_id}/confirm", {
          params: { path: { action_id: action.id }, header: { "Idempotency-Key": confirmKey(scope) } },
        }))
        : await call(api.POST("/api/actions/{action_id}/cancel", path));
      onChange(card);
      close(card);
    } catch (e) {
      const failure = e instanceof ApiError ? e : null;
      if (failure?.code === "network" || failure?.code === "timeout") {
        // Ответ потерялся: исход узнаём по текущему статусу карточки.
        const card = await reread();
        if (card && card.status !== action.status) close(card);
        else setError(operation === "confirm"
          ? "Не удалось узнать результат. Повтор безопасен: вторая заявка не появится."
          : "Не удалось узнать результат. Карточка не изменилась — можно повторить.");
      } else if (failure?.code === "conflict" || failure?.code === "not_found") {
        // Карточку уже изменили в другом месте — показываем, что на сервере сейчас.
        close(await reread(), failure.message);
      } else {
        // 503 и прочее: карточка не изменилась, ключ сохраняем для повтора.
        setError(failure?.message ?? "Не удалось выполнить действие. Попробуй ещё раз.");
      }
    } finally {
      setBusy(false);
    }
  }

  const buttons = <>
    {canConfirm(action) && <Button disabled={busy} onClick={() => setDialog("confirm")}>Отправить на согласование</Button>}
    {canCancel(action) && <Button tone="secondary" disabled={busy} onClick={() => setDialog("cancel")}>
      {action.status === "draft" ? "Отменить черновик" : "Отменить заявку"}</Button>}
    {footer}
  </>;
  return <>
    <ActionCard action={action} footer={<div className="button-row">{buttons}</div>} />
    {notice && <p className="muted" role="status">{notice}</p>}
    <ConfirmDialog open={dialog === "confirm"} title="Отправить заявку?" confirmLabel="Отправить" busy={busy} error={error}
      onConfirm={() => run("confirm")} onClose={() => close(null)}>
      <p>«{action.title}» уйдёт на согласование{action.fields["Согласует"] ? ` — ${action.fields["Согласует"]}` : ""}.</p>
    </ConfirmDialog>
    <ConfirmDialog open={dialog === "cancel"} title="Отменить заявку?" confirmLabel="Отменить заявку" busy={busy} error={error}
      onConfirm={() => run("cancel")} onClose={() => close(null)}>
      <p>«{action.title}» будет отменена. Вернуть её не получится — понадобится новая заявка.</p>
    </ConfirmDialog>
  </>;
}
