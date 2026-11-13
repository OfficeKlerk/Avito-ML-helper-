import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test } from "vitest";
import { routes } from "../../app/routes";
import { SessionProvider } from "../../app/session";
import { fixtureFetch } from "../../shared/api/fixtures";

function open(path: string, pick: Record<string, string> = {}) {
  const sent: string[] = [];
  const fixtures = fixtureFetch(pick);
  const transport = async (request: Request) => {
    sent.push(`${request.method} ${new URL(request.url).pathname} ${await request.clone().text()}`);
    return fixtures(request);
  };
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  render(<SessionProvider fetch={transport}><RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} /></SessionProvider>);
  return sent;
}

afterEach(() => sessionStorage.clear());

const cards = () => screen.getAllByRole("listitem");

test("список: новые и прочитанные, переходы к задаче и заявке", async () => {
  open("/notifications");
  expect(await screen.findByText(/отправлена на согласование/)).toBeInTheDocument();
  expect(cards()).toHaveLength(2);
  expect(within(cards()[0]).getByText("Новое")).toBeInTheDocument();
  expect(within(cards()[0]).getByRole("link", { name: "К заявке" })).toHaveAttribute("href", "/actions/act_anna_dayoff_1");
  expect(within(cards()[1]).getByRole("link", { name: "К задаче" })).toHaveAttribute("href", "/onboarding/tasks/t_join_channels");
  expect(within(cards()[1]).queryByRole("button", { name: "Отметить прочитанным" })).not.toBeInTheDocument();
});

test("отметка прочтения берёт запись из ответа сервера и не дублирует её", async () => {
  const sent = open("/notifications");
  fireEvent.click(await screen.findByRole("button", { name: "Отметить прочитанным" }));
  expect(await within(cards()[0]).findByText("Прочитано")).toBeInTheDocument();
  expect(cards()).toHaveLength(2);
  expect(sent).toContain('PATCH /api/notifications/ntf_anna_002 {"read":true}');
  expect(screen.queryByRole("button", { name: "Отметить прочитанным" })).not.toBeInTheDocument();
});

test("ошибка отметки показана, уведомление остаётся новым", async () => {
  open("/notifications", { notification_mark_read: "foreign_notification" });
  fireEvent.click(await screen.findByRole("button", { name: "Отметить прочитанным" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Уведомление не найдено.");
  expect(within(cards()[0]).getByText("Новое")).toBeInTheDocument();
});

test("ошибка загрузки: «Повторить» показывает загрузку и перечитывает список", async () => {
  let failures = 1;
  const fixtures = fixtureFetch();
  const transport = async (request: Request) => (new URL(request.url).pathname === "/api/notifications" && failures-- > 0
    ? Response.json({ error: { code: "forbidden", message: "Нет доступа к уведомлениям." } }, { status: 403 })
    : fixtures(request));
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  render(<SessionProvider fetch={transport}><RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/notifications"] })} /></SessionProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа к уведомлениям.");
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(screen.getByRole("status")).toHaveTextContent("Загружаем");
  expect(await screen.findByText(/отправлена на согласование/)).toBeInTheDocument();
});

test("прямая ссылка открывает одно уведомление", async () => {
  open("/notifications/ntf_anna_001");
  expect(await screen.findByRole("link", { name: "Все уведомления" })).toBeInTheDocument();
  expect(cards()).toHaveLength(1);
});
