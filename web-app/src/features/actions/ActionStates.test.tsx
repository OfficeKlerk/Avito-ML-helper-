import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { routes } from "../../app/routes";
import { SessionProvider } from "../../app/session";
import type { Schemas } from "../../shared/api/client";
import { ActionItem } from "./ActionItem";
import { MAX_POLLS, POLL_MS } from "./polling";

type Card = Schemas["ActionCard"];

const base: Card = {
  id: "act_1", type: "absence_request", status: "draft", title: "Отгул 18.11.2026",
  fields: { "Тип": "Отгул", "Даты": "18.11.2026", "Новое поле": "сохраняется" }, external_id: "req_1",
  result: null, error: null, created_at: "2026-11-13T10:00:00+03:00", updated_at: "2026-11-13T10:00:00+03:00", fulfilled_at: null,
};
const card = (patch: Partial<Card>): Card => ({ ...base, ...patch });

beforeEach(() => sessionStorage.setItem("ai-buddy.token", "jwt-anna"));
afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

// R5: каждое состояние карточки — своя подпись и только допустимые действия.
test.each([
  [card({}), "Черновик", ["Отправить на согласование", "Отменить черновик"]],
  [card({ status: "submitted" }), "На согласовании", ["Отменить заявку"]],
  [card({ status: "approved" }), "Согласована", []],
  [card({ type: "access_request", status: "approved" }), "Согласована, доступ ещё не выдан", []],
  [card({ type: "access_request", status: "approved", fulfilled_at: "2026-11-14T12:00:00+03:00" }), "Доступ выдан", []],
  [card({ status: "rejected", result: { message: "Отклонено: в эти даты релиз.", external_ref: null } }), "Отклонена", []],
  [card({ status: "cancelled", result: { message: "Заявка отправлена на согласование.", external_ref: null } }), "Отменена", []],
  [card({ status: "failed", error: "Сервис заявок не ответил." }), "Ошибка отправки", []],
])("состояние %#: %s", (action, label, buttons) => {
  render(<SessionProvider fetch={async () => new Response(null, { status: 500 })}><ActionItem action={action} onChange={() => {}} /></SessionProvider>);
  expect(screen.getByText(label)).toBeInTheDocument();
  expect(screen.getByText("сохраняется")).toBeInTheDocument(); // неизвестное поле не теряется
  expect(screen.queryAllByRole("button").map((b) => b.textContent)).toEqual(buttons);
  if (action.status === "rejected") expect(screen.getByText("Отклонено: в эти даты релиз.")).toBeInTheDocument();
  if (action.status === "cancelled") expect(screen.queryByText(/отправлена на согласование/)).not.toBeInTheDocument();
  if (action.status === "failed") expect(screen.getByText("Сервис заявок не ответил.")).toBeInTheDocument();
});

/** Список заявок, где каждое следующее чтение отдаёт следующую версию карточек. */
function openList(versions: Card[][]) {
  let reads = 0;
  const transport = async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/me") return Response.json({ id: "u_anna", login: "intern_anna", name: "Анна", role: "intern", team: null, mentor: null, manager: null, start_date: null, internship_week: null, program: null });
    reads += 1;
    return Response.json({ actions: versions[Math.min(reads - 1, versions.length - 1)] });
  };
  const view = render(<SessionProvider fetch={transport}><RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/actions"] })} /></SessionProvider>);
  return { reads: () => reads, view };
}

// По одному интервалу: в жизни срабатывания разделены 10 секундами, и каждый ответ успевает прийти.
async function tick(times = 1) {
  for (let i = 0; i < times; i++) {
    await vi.advanceTimersByTimeAsync(POLL_MS);
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

test("опрос: открытая заявка перечитывается, после решения опрос останавливается", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }); // только опрос; ответы сети идут как обычно
  const list = openList([[card({ status: "submitted" })], [card({ status: "approved" })]]);
  await vi.waitFor(() => expect(screen.getByText("На согласовании")).toBeInTheDocument());
  await tick();
  await vi.waitFor(() => expect(within(screen.getByRole("article")).getByText("Согласована")).toBeInTheDocument());
  await tick(3);
  expect(list.reads()).toBe(2);
});

test("опрос: согласованный доступ ждёт выдачи, выдача видна и опрос стоп", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }); // только опрос; ответы сети идут как обычно
  const access = card({ type: "access_request", status: "approved", title: "Доступ к GitLab" });
  const list = openList([[access], [access], [{ ...access, fulfilled_at: "2026-11-14T12:00:00+03:00" }]]);
  await vi.waitFor(() => expect(screen.getByText("Согласована, доступ ещё не выдан")).toBeInTheDocument());
  await tick(2);
  await vi.waitFor(() => expect(screen.getByText("Доступ выдан")).toBeInTheDocument());
  await tick(3);
  expect(list.reads()).toBe(3);
});

test("опрос ограничен, не идёт в скрытой вкладке и останавливается при уходе", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }); // только опрос; ответы сети идут как обычно
  const list = openList([[card({ status: "submitted" })]]);
  await vi.waitFor(() => expect(screen.getByText("На согласовании")).toBeInTheDocument());
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  await tick(5);
  expect(list.reads()).toBe(1);
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  await tick(MAX_POLLS + 10);
  await vi.waitFor(() => expect(list.reads()).toBe(1 + MAX_POLLS));
  list.view.unmount(); // выход или переход на другую страницу
  await tick(5);
  expect(list.reads()).toBe(1 + MAX_POLLS);
});
