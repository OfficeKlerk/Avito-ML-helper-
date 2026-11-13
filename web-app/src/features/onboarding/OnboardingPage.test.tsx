import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { routes } from "../../app/routes";
import { SessionProvider } from "../../app/session";
import { fixtureFetch } from "../../shared/api/fixtures";
import { describeDue, todayInMoscow } from "./dates";
import { SafeLink } from "./OnboardingPage";
import { adaptationRefreshInterval } from "./taskLinks";
import type { Schemas } from "../../shared/api/client";

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

type Plan = Schemas["Onboarding"];
const planFixture = async (example = "anna_week1"): Promise<Plan> =>
  (await fixtureFetch({ onboarding_get: example })(new Request("http://localhost/api/onboarding"))).json();

function openLive(path: string, transport: (request: Request) => Promise<Response>) {
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return {
    router,
    ...render(<SessionProvider fetch={transport}><RouterProvider router={router} /></SessionProvider>),
  };
}

test("задача открывает редактируемый вопрос и связанную заявку, возврат перечитывает план", async () => {
  const fixture = fixtureFetch();
  const plan = await planFixture();
  const task = plan.stages.flatMap((stage) => stage.tasks).find((item) => item.id === "t_request_accesses")!;
  task.related_action_id = "act_anna_dayoff_1";
  const posts = vi.fn(fixture);
  const { router } = openLive("/onboarding/tasks/t_request_accesses", (request) =>
    new URL(request.url).pathname === "/api/onboarding" ? Promise.resolve(Response.json(plan))
      : request.method === "POST" ? posts(request) : fixture(request));

  fireEvent.click(await screen.findByRole("link", { name: "Спросить в чате" }));
  expect(await screen.findByRole("textbox", { name: "Сообщение" })).toHaveValue(`Помоги с задачей «${task.title}». Что нужно сделать?`);
  expect(router.state.location.search).toBe("?task=t_request_accesses");
  expect(posts).not.toHaveBeenCalled();

  fireEvent.click(await screen.findByRole("link", { name: /Как оформить отгул или отпуск/ }));
  await screen.findByRole("heading", { name: "Отгул" });
  fireEvent.click(await screen.findByRole("link", { name: "Вернуться в чат" }));
  expect(await screen.findByRole("link", { name: "Вернуться к задаче" })).toHaveAttribute("href", "/onboarding/tasks/t_request_accesses");
  fireEvent.click(screen.getByRole("link", { name: "Вернуться к задаче" }));
  fireEvent.click(await screen.findByRole("link", { name: "Связанная заявка" }));
  expect(await screen.findByRole("heading", { name: "Отгул 13.11.2026" })).toBeInTheDocument();
  task.status = "done";
  fireEvent.click(screen.getByRole("link", { name: "Вернуться к задаче" }));
  expect(await screen.findByText("Выполнено")).toBeInTheDocument();
});

test("фоновая ошибка оставляет план на экране, повтор обновляет данные", async () => {
  const fixture = fixtureFetch();
  const plan = await planFixture();
  let reads = 0;
  openLive("/onboarding", (request) => {
    if (new URL(request.url).pathname !== "/api/onboarding") return fixture(request);
    reads++;
    return Promise.resolve(reads === 2
      ? Response.json({ error: { code: "internal", message: "Сбой чтения." } }, { status: 500 })
      : Response.json({ ...plan, progress: reads === 1 ? 7 : 23 }));
  });

  expect(await screen.findByText("7%")).toBeInTheDocument();
  fireEvent(window, new Event("focus"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось обновить план. Сбой чтения.");
  expect(screen.getByText("7%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByText("23%")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("план обновляется на видимой вкладке, пересчитывает срок в полночь по Москве и останавливается после выхода", async () => {
  const fixture = fixtureFetch();
  const plan = await planFixture();
  const task = plan.stages.flatMap((stage) => stage.tasks).find((item) => item.id === "t_join_channels")!;
  task.due_date = "2026-11-13";
  vi.setSystemTime(new Date("2026-11-13T20:59:50Z"));

  let hidden = false;
  const visibility = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  let reads = 0;
  try {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    openLive("/onboarding/tasks/t_join_channels", async (request) => {
      if (new URL(request.url).pathname !== "/api/onboarding") return fixture(request);
      reads++;
      return Response.json(plan);
    });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(reads).toBe(1);
    expect(screen.getByText("Срок сегодня")).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(adaptationRefreshInterval));
    expect(reads).toBe(2);
    expect(screen.getByText("Просрочено, срок 13 ноября")).toBeInTheDocument();

    hidden = true;
    fireEvent(document, new Event("visibilitychange"));
    await act(() => vi.advanceTimersByTimeAsync(2 * adaptationRefreshInterval));
    expect(reads).toBe(2);

    hidden = false;
    fireEvent(document, new Event("visibilitychange"));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(reads).toBe(3);
    fireEvent.click(screen.getByRole("button", { name: "Выйти из аккаунта" }));
    await act(() => vi.advanceTimersByTimeAsync(2 * adaptationRefreshInterval));
    expect(reads).toBe(3);
    expect(screen.getByRole("heading", { name: "Вход в AI-buddy" })).toBeInTheDocument();
  } finally {
    visibility.mockRestore();
  }
});

test("пустой план другой команды и полностью завершённый план имеют отдельные сообщения", async () => {
  const plan = await planFixture();
  const fixture = fixtureFetch();
  let empty = true;
  openLive("/onboarding", async (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/me") {
      const user = await (await fixture(request)).json();
      return Response.json({ ...user, id: "u_max", name: "Максим", team: { ...user.team, name: "Авито Авто" } });
    }
    if (path !== "/api/onboarding") return fixture(request);
    return Response.json(empty ? { progress: 0, next_steps: [], stages: [] } : {
      progress: 100, next_steps: [], stages: plan.stages.map((stage) => ({
        ...stage, status: "done", tasks: stage.tasks.map((task) => ({ ...task, status: "done" })),
      })),
    });
  });

  expect(await screen.findByText(/Плана адаптации пока нет/)).toBeInTheDocument();
  expect(screen.getByText("Авито Авто")).toBeInTheDocument();
  empty = false;
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText("Все задачи выполнены.")).toBeInTheDocument();
  expect(screen.getByText("100%")).toBeInTheDocument();
  expect(screen.queryByText(/Просрочено/)).not.toBeInTheDocument();
});
