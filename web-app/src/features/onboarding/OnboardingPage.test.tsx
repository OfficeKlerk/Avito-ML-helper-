import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { routes } from "../../app/routes";
import { SessionProvider } from "../../app/session";
import { fixtureFetch } from "../../shared/api/fixtures";
import { describeDue, todayInMoscow } from "./dates";
import { SafeLink } from "./OnboardingPage";

function open(path: string, pick: Record<string, string> = {}) {
  const sent: { method: string; path: string; body: string }[] = [];
  const fixtures = fixtureFetch(pick);
  const transport = async (request: Request) => {
    sent.push({ method: request.method, path: new URL(request.url).pathname, body: await request.clone().text() });
    return fixtures(request);
  };
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  render(<SessionProvider fetch={transport}><RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} /></SessionProvider>);
  return sent;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-13T09:00:00+03:00"));
});
afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
});

test("план: прогресс, следующие шаги с причинами, этапы и сроки по Москве", async () => {
  open("/onboarding");
  expect(await screen.findByText("7%")).toBeInTheDocument();
  const steps = within(screen.getByRole("region", { name: "Что сделать дальше" })).getAllByRole("listitem");
  expect(steps).toHaveLength(3);
  expect(steps[0]).toHaveTextContent("Задача уже в работе");
  const week1 = screen.getByRole("region", { name: "Первая неделя" });
  expect(within(week1).getByText("Сейчас")).toBeInTheDocument();
  const row = (id: string) => week1.querySelector(`a[href="/onboarding/tasks/${id}"]`)!.closest("li")!;
  // Срок 11 ноября прошёл: незавершённая задача просрочена, выполненная — нет.
  expect(row("t_join_channels")).toHaveTextContent("Просрочено, срок 11 ноября");
  expect(row("t_meet_team")).toHaveTextContent("Срок 11 ноября");
  expect(row("t_meet_team")).not.toHaveTextContent("Просрочено");
});

test("смена статуса уходит на сервер, после чего план перечитывается", async () => {
  const sent = open("/onboarding/tasks/t_join_channels");
  fireEvent.click(await screen.findByRole("button", { name: "Отметить выполненной" }));
  await vi.waitFor(() => expect(sent.filter((r) => r.path === "/api/onboarding")).toHaveLength(2));
  expect(sent).toContainEqual({ method: "PATCH", path: "/api/onboarding/tasks/t_join_channels", body: '{"status":"done"}' });
});

test("отказ сервера показан, успех не изображается", async () => {
  const sent = open("/onboarding/tasks/t_join_channels", { onboarding_task_patch: "bad_status" });
  fireEvent.click(await screen.findByRole("button", { name: "Отметить выполненной" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Такого статуса задачи нет.");
  expect(screen.getByText("В работе")).toBeInTheDocument();
  expect(sent.filter((r) => r.path === "/api/onboarding")).toHaveLength(1);
});

test("задача на доступ предупреждает, что завершится после выдачи", async () => {
  open("/onboarding/tasks/t_request_accesses");
  expect(await screen.findByText(/завершится, когда доступ выдадут/)).toBeInTheDocument();
  expect(screen.getByText("Как запросить доступы — документ базы знаний")).toBeInTheDocument();
});

test("сроки и ссылки", () => {
  expect(todayInMoscow(new Date("2026-11-13T22:30:00Z"))).toBe("2026-11-14"); // в Москве уже следующий день
  expect(describeDue("2026-11-13", false, "2026-11-13")).toEqual({ label: "Срок сегодня", tone: "warning" });
  expect(describeDue("2026-11-12", true, "2026-11-13")?.tone).toBe("neutral");
  expect(describeDue(null, false)).toBeNull();
  render(<><SafeLink title="Вики" url="https://wiki.example" /><SafeLink title="Опасно" url="javascript:alert(1)" /></>);
  expect(screen.getByRole("link", { name: "Вики" })).toHaveAttribute("href", "https://wiki.example");
  expect(screen.queryByRole("link", { name: "Опасно" })).not.toBeInTheDocument();
});
