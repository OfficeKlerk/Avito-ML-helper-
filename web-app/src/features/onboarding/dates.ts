// Сроки задач — календарные даты в Europe/Moscow. Сравниваем строки YYYY-MM-DD, без часовых сдвигов браузера.
const moscowDay = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" });
const ruDay = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", timeZone: "UTC" });

export const todayInMoscow = (now = new Date()): string => moscowDay.format(now);

export const formatDay = (day: string): string => ruDay.format(new Date(`${day}T00:00:00Z`));

export type Due = { label: string; tone: "neutral" | "warning" | "danger" };

/** Подпись срока: просрочено, сегодня или дата. Выполненная задача не бывает просроченной. */
export function describeDue(due: string | null, done: boolean, today = todayInMoscow()): Due | null {
  if (!due) return null;
  if (done) return { label: `Срок ${formatDay(due)}`, tone: "neutral" };
  if (due < today) return { label: `Просрочено, срок ${formatDay(due)}`, tone: "danger" };
  if (due === today) return { label: "Срок сегодня", tone: "warning" };
  return { label: `Срок ${formatDay(due)}`, tone: "neutral" };
}
