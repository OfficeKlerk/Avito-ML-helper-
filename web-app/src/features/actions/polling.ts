import { useEffect } from "react";
import type { Schemas } from "../../shared/api/client";

export const POLL_MS = 10_000;
// Не больше 10 минут опроса за один показ страницы: дальше статус обновится при следующем открытии.
export const MAX_POLLS = 60;

/** Заявка ещё может измениться без участия пользователя: ждёт решения или выдачи доступа. */
export const isOpen = (card: Schemas["ActionCard"]) =>
  card.status === "submitted" || (card.type === "access_request" && card.status === "approved" && !card.fulfilled_at);

/**
 * R4: пока есть открытые заявки, перечитываем их раз в POLL_MS. Каждое чтение core-api синхронизирует с corp-mock.
 * Скрытая вкладка не опрашивает; при уходе со страницы или выходе опрос останавливается вместе с компонентом.
 */
export function usePolling(active: boolean, tick: () => void) {
  useEffect(() => {
    if (!active) return;
    let polls = 0;
    const timer = setInterval(() => {
      if (document.hidden) return;
      polls += 1;
      if (polls > MAX_POLLS) clearInterval(timer);
      else tick();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [active, tick]);
}
