import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test } from "vitest";
import { fixtureFetch } from "../shared/api/fixtures";
import { routes } from "./routes";
import { SessionProvider } from "./session";

function open(path: string, pick: Record<string, string> = {}, transport = fixtureFetch(pick)) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <SessionProvider fetch={transport}>
      <RouterProvider router={router} />
    </SessionProvider>,
  );
  return router;
}

function signIn(password: string) {
  fireEvent.change(screen.getByLabelText("Логин"), { target: { value: "intern_anna" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}

afterEach(() => sessionStorage.clear());

test("без входа — форма входа; неверный пароль — понятная ошибка; затем вход и выход", async () => {
  const pick: Record<string, string> = { auth_login: "wrong_password" };
  const router = open("/?tab=plan", pick);
  expect(router.state.location.pathname).toBe("/login");

  signIn("wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent(/парол/i);
  expect(sessionStorage.length).toBe(0);

  delete pick.auth_login;
  signIn("buddy2026");
  expect(await screen.findByRole("heading", { name: "Привет, Анна Соколова" })).toBeInTheDocument();
  expect(within(screen.getByRole("main")).getByText("Авито Доставка")).toBeInTheDocument();
  expect(screen.getByText("Стажёр")).toBeInTheDocument();
  expect(router.state.location).toMatchObject({ pathname: "/", search: "?tab=plan" });

  fireEvent.click(screen.getByRole("button", { name: "Выйти из аккаунта" }));
  expect(await screen.findByRole("heading", { name: "Вход в AI-buddy" })).toBeInTheDocument();
  expect(screen.queryByText("Анна Соколова")).not.toBeInTheDocument();
  expect(sessionStorage.length).toBe(0);
});

test("сохранённый вход восстанавливается через /api/me", async () => {
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  open("/");
  expect(screen.getByRole("status")).toHaveTextContent("Проверяем вход");
  expect(await screen.findByRole("heading", { name: "Привет, Анна Соколова" })).toBeInTheDocument();
});

test("истёкший токен: сессия очищается, открывается вход", async () => {
  sessionStorage.setItem("ai-buddy.token", "expired");
  const router = open("/", { me: "no_token" });
  expect(await screen.findByRole("heading", { name: "Вход в AI-buddy" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect(sessionStorage.getItem("ai-buddy.token")).toBeNull();
});

test("после перезагрузки входа открывается исходная ссылка вместе с запросом и якорем", async () => {
  const target = "/actions/act_anna_dayoff_1?from=notifications#status";
  const router = open(`/login?${new URLSearchParams({ returnTo: target })}`);
  signIn("buddy2026");
  expect(await screen.findByRole("heading", { name: "Отгул 13.11.2026" })).toBeInTheDocument();
  expect(screen.getByText("Черновик")).toBeInTheDocument();
  expect(router.state.location).toMatchObject({
    pathname: "/actions/act_anna_dayoff_1", search: "?from=notifications", hash: "#status",
  });
});

test("уведомление ведёт к задаче, навигация сохраняется и указывает текущий раздел", async () => {
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  open("/notifications/ntf_anna_001");
  const nav = within(await screen.findByRole("navigation", { name: "Основная навигация" }));
  for (const name of ["Профиль", "Чат", "Адаптация", "Заявки", "Уведомления"]) {
    expect(nav.getByRole("link", { name })).toBeInTheDocument();
  }
  expect(nav.getByRole("link", { name: "Уведомления" })).toHaveAttribute("aria-current", "page");
  fireEvent.click(await screen.findByRole("link", { name: "К задаче" }));
  expect(await screen.findByRole("heading", { name: "Попроси добавить тебя в ключевые каналы и чаты" })).toBeInTheDocument();
  expect(nav.getByRole("link", { name: "Адаптация" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("main")).toHaveFocus();
});

test("неизвестный адрес показывает 404 внутри оболочки", async () => {
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  open("/missing");
  expect(await screen.findByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "В профиль" })).toHaveAttribute("href", "/");
  expect(screen.getByRole("navigation")).toBeInTheDocument();
});

test("ошибка API оставляет навигацию и позволяет повторить загрузку раздела", async () => {
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  const pick = { action_get: "foreign_card" };
  open("/actions/act_anna_dayoff_1", pick);
  expect(await screen.findByRole("alert")).toHaveTextContent("Действие не найдено.");
  expect(screen.getByRole("navigation")).toBeInTheDocument();
  const retry = screen.getByRole("button", { name: "Повторить" });
  pick.action_get = "draft";
  fireEvent.click(retry);
  expect(await screen.findByRole("heading", { name: "Отгул 13.11.2026" })).toBeInTheDocument();
});
