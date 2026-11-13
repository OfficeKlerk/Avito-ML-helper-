import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test } from "vitest";
import { fixtureFetch } from "../shared/api/fixtures";
import { routes } from "./routes";
import { SessionProvider } from "./session";

function open(path: string, pick: Record<string, string> = {}) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <SessionProvider fetch={fixtureFetch(pick)}>
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
  expect(screen.getByText("Авито Доставка")).toBeInTheDocument();
  expect(screen.getByText("Стажёр")).toBeInTheDocument();
  expect(router.state.location).toMatchObject({ pathname: "/", search: "?tab=plan" });

  fireEvent.click(screen.getByRole("button", { name: "Выйти" }));
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
