import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, expect, test } from "vitest";
import { routes } from "../../app/routes";
import { SessionProvider } from "../../app/session";
import { fixtureFetch } from "../../shared/api/fixtures";

type Sent = { method: string; path: string; key: string | null };

beforeAll(() => {
  // В jsdom нет модальных диалогов.
  HTMLDialogElement.prototype.showModal = function showModal() { this.open = true; };
  HTMLDialogElement.prototype.close = function close() { this.open = false; };
});
afterEach(() => sessionStorage.clear());

/** Открывает страницу; transport перехватывает запросы, остальное отвечает примерами из fixtures. */
function open(path: string, pick: Record<string, string> = {}, override?: (r: Request) => Promise<Response> | null) {
  const sent: Sent[] = [];
  const fixtures = fixtureFetch(pick);
  const transport = async (request: Request) => {
    sent.push({ method: request.method, path: new URL(request.url).pathname, key: request.headers.get("Idempotency-Key") });
    return override?.(request) ?? fixtures(request);
  };
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  render(<SessionProvider fetch={transport}><RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} /></SessionProvider>);
  return sent;
}

const CONFIRM = "/api/actions/act_anna_dayoff_1/confirm";
const dialog = () => screen.getByRole("dialog");
async function startConfirm() {
  fireEvent.click(await screen.findByRole("button", { name: "Отправить на согласование" }));
  expect(dialog()).toHaveTextContent("уйдёт на согласование — Ольга Крылова");
  fireEvent.click(within(dialog()).getByRole("button", { name: "Отправить" }));
}

test("черновик: поля карточки и явное подтверждение отправляют заявку", async () => {
  const sent = open("/actions/act_anna_dayoff_1");
  expect(await screen.findByText("Личные дела")).toBeInTheDocument();
  expect(screen.getByText("Черновик")).toBeInTheDocument();
  expect(sent.some((r) => r.path === CONFIRM)).toBe(false); // без клика ничего не уходит
  await startConfirm();
  expect(await screen.findByText("На согласовании")).toBeInTheDocument();
  expect(sent.filter((r) => r.path === CONFIRM)).toHaveLength(1);
  expect(Object.keys(sessionStorage).some((k) => k.startsWith("ai-buddy.confirm."))).toBe(false); // исход известен — ключ забыт
  expect(screen.queryByRole("button", { name: "Отправить на согласование" })).not.toBeInTheDocument();
});

test("503: ошибка в диалоге, повтор идёт с тем же ключом, карточка остаётся черновиком", async () => {
  const sent = open("/actions/act_anna_dayoff_1", { action_confirm: "corp_unavailable" });
  await startConfirm();
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent("Сервис заявок временно недоступен");
  fireEvent.click(within(dialog()).getByRole("button", { name: "Отправить" }));
  await within(dialog()).findByRole("alert");
  const keys = sent.filter((r) => r.path === CONFIRM).map((r) => r.key);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(screen.getByText("Черновик")).toBeInTheDocument();
});

test("ответ потерялся: карточка перечитывается, повтор безопасен и с тем же ключом", async () => {
  let lose = true;
  const sent = open("/actions/act_anna_dayoff_1", {}, (r) => {
    if (new URL(r.url).pathname === CONFIRM && lose) {
      lose = false;
      return Promise.reject(new TypeError("Failed to fetch"));
    }
    return null;
  });
  await startConfirm();
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent("Повтор безопасен");
  expect(sent.filter((r) => r.method === "GET" && r.path === "/api/actions/act_anna_dayoff_1")).toHaveLength(2);
  fireEvent.click(within(dialog()).getByRole("button", { name: "Отправить" }));
  expect(await screen.findByText("На согласовании")).toBeInTheDocument();
  const keys = sent.filter((r) => r.path === CONFIRM).map((r) => r.key);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

test("конфликт: показываем текст сервера и перечитанную карточку", async () => {
  const sent = open("/actions/act_anna_dayoff_1", { action_confirm: "already_cancelled" });
  await startConfirm();
  expect(await screen.findByRole("status")).toHaveTextContent("Это действие уже отменено.");
  expect(sent.filter((r) => r.method === "GET" && r.path === "/api/actions/act_anna_dayoff_1")).toHaveLength(2);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("двойной клик отправляет один запрос", async () => {
  const sent = open("/actions/act_anna_dayoff_1");
  fireEvent.click(await screen.findByRole("button", { name: "Отправить на согласование" }));
  const send = within(dialog()).getByRole("button", { name: "Отправить" });
  fireEvent.click(send);
  fireEvent.click(send);
  expect(await screen.findByText("На согласовании")).toBeInTheDocument();
  expect(sent.filter((r) => r.path === CONFIRM)).toHaveLength(1);
});

test("отмена черновика и отказ отменить согласованную", async () => {
  open("/actions/act_anna_dayoff_1");
  fireEvent.click(await screen.findByRole("button", { name: "Отменить черновик" }));
  fireEvent.click(within(dialog()).getByRole("button", { name: "Отменить заявку" }));
  expect(await screen.findByText("Отменена")).toBeInTheDocument();
  expect(screen.getByText("Заявка отменена.")).toBeInTheDocument();
  expect(screen.queryByText(/отправлена на согласование/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Отменить/ })).not.toBeInTheDocument();
});

test("отменить уже согласованную нельзя: сервер объясняет, карточка перечитана", async () => {
  open("/actions/act_anna_dayoff_1", { action_cancel: "already_approved" });
  fireEvent.click(await screen.findByRole("button", { name: "Отменить черновик" }));
  fireEvent.click(within(dialog()).getByRole("button", { name: "Отменить заявку" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Заявка уже согласована, отменить её нельзя.");
});

test("список: у каждой карточки свои действия и ссылка", async () => {
  open("/actions");
  const cards = await screen.findAllByRole("article");
  expect(cards).toHaveLength(2);
  expect(within(cards[0]).getByRole("link", { name: /Открыть заявку/ })).toBeInTheDocument();
});
