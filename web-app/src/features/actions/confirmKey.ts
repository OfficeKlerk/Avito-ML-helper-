import { newIdempotencyKey } from "../../shared/api/client";

// R2: один Idempotency-Key на попытку подтверждения карточки, пока исход не выяснен.
// Хранится и в памяти, и в sessionStorage — переживает двойной клик, таймаут и перезагрузку вкладки.
const memory = new Map<string, string>();
const storageKey = (scope: string) => `ai-buddy.confirm.${scope}`;

export function confirmKey(scope: string): string {
  let key = memory.get(scope);
  if (!key) {
    try {
      key = sessionStorage.getItem(storageKey(scope)) ?? undefined;
    } catch {
      // хранилище запрещено браузером — хватит памяти
    }
  }
  key ??= newIdempotencyKey();
  memory.set(scope, key);
  try {
    sessionStorage.setItem(storageKey(scope), key);
  } catch {
    // см. выше
  }
  return key;
}

/** Исход известен (заявка ушла, отменена или карточки нет) — следующая попытка будет новой. */
export function forgetConfirmKey(scope: string) {
  memory.delete(scope);
  try {
    sessionStorage.removeItem(storageKey(scope));
  } catch {
    // см. выше
  }
}
