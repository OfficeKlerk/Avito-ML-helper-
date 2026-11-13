import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { routes } from "../../app/routes";
import { SessionProvider } from "../../app/session";
import { fixtureFetch } from "../../shared/api/fixtures";
import { splitDocument } from "./documents";
import { Markdown } from "./Markdown";
import { clearPendingTurn } from "./pendingTurn";

function open(path = "/chat", transport = fixtureFetch()) {
  sessionStorage.setItem("ai-buddy.token", "jwt-anna");
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return {
    router,
    ...render(<SessionProvider fetch={transport}><RouterProvider router={router} /></SessionProvider>),
  };
}

function typeMessage(text: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Сообщение" }), { target: { value: text } });
}

afterEach(() => {
  vi.useRealTimers();
  clearPendingTurn();
  sessionStorage.clear();
});

test("загружает историю с лимитом 50, показывает сообщения в порядке API и метаданные источника", async () => {
  const fixture = fixtureFetch();
  const transport = vi.fn(fixture);
  open("/chat", transport);
  const history = await screen.findByRole("list", { name: "История диалога" });
  const messages = [...history.children];
  expect(messages).toHaveLength(4);
  expect(messages[0]).toHaveTextContent("ВыЧто мне делать дальше?");
  expect(messages[1]).toHaveTextContent("AI-buddy");
  expect(messages[3]).toHaveTextContent("Отгул оформляется так");
  expect(await screen.findByText(/Тестовая инструкция/)).toBeInTheDocument();
  expect(screen.getByText("2 нояб. 2026 г.")).toHaveAttribute("datetime", "2026-11-02");
  expect(transport.mock.calls.map(([request]) => new URL(request.url).search)).toContain("?limit=50");
});

test("пока ждём ответ, повторный submit пропускается, навигация доступна, успешные сообщения приходят от сервера", async () => {
  const fixture = fixtureFetch({ chat_messages_list: "no_messages", chat_message_post: "agent_degraded" });
  let finish: (response: Response) => void = () => {};
  const transport = vi.fn(async (request: Request) => request.method === "POST"
    ? new Promise<Response>((resolve) => { finish = resolve; })
    : fixture(request));
  open("/chat", transport);
  await screen.findByText(/Задай первый вопрос/);
  typeMessage("Что мне делать дальше?");
  const submit = screen.getByRole("button", { name: "Отправить" });
  const form = submit.closest("form")!;
  fireEvent.click(submit);
  fireEvent.submit(form);
  expect(screen.getByRole("status")).toHaveTextContent("Ждём ответа помощника…");
  expect(screen.getByRole("button", { name: "Отправляем…" })).toBeDisabled();
  expect(screen.queryByRole("list", { name: "История диалога" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Заявки" })).toBeEnabled();
  const posts = await waitFor(() => {
    const requests = transport.mock.calls.map(([request]) => request).filter((request) => request.method === "POST");
    expect(requests).not.toHaveLength(0);
    return requests;
  });
  expect(posts).toHaveLength(1);
  expect(posts[0].headers.get("Idempotency-Key")).toMatch(/^[a-f0-9]{32}$/);
  finish(await fixture(posts[0]));
  expect(await screen.findByText("Упрощённый ответ")).toBeInTheDocument();
  expect(screen.getByText("Что мне делать дальше?")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Сообщение" })).toHaveValue("");
});

test("таймаут и 429 повторяют тот же ключ и текст, в том числе при повторном открытии чата", async () => {
  const fixture = fixtureFetch({ chat_messages_list: "no_messages" });
  const posts: { key: string | null; text: string }[] = [];
  const transport = async (request: Request) => {
    if (request.method !== "POST") return fixture(request);
    posts.push({ key: request.headers.get("Idempotency-Key"), text: (await request.json()).text });
    if (posts.length === 1) {
      return new Promise<Response>((_, reject) => {
        request.signal.addEventListener("abort", () => reject(request.signal.reason), { once: true });
      });
    }
    if (posts.length === 2) return Response.json({ error: { code: "rate_limited" } }, { status: 429 });
    const response = await fixture(request);
    const exchange = await response.json();
    exchange.assistant_message.status = "error";
    return Response.json(exchange);
  };
  const { router } = open("/chat", transport);
  await screen.findByText(/Задай первый вопрос/);
  typeMessage("Что мне делать дальше?");
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  vi.useRealTimers();
  expect(await screen.findByRole("alert")).toHaveTextContent(/вовремя/);

  await act(() => router.navigate("/"));
  await act(() => router.navigate("/chat"));
  await screen.findByText(/Задай первый вопрос/);
  expect(screen.getByRole("textbox", { name: "Сообщение" })).toHaveAttribute("readonly");
  fireEvent.click(screen.getByRole("button", { name: "Повторить отправку" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/чуть позже/);
  fireEvent.click(screen.getByRole("button", { name: "Повторить отправку" }));
  expect(await screen.findByText("Не удалось ответить")).toBeInTheDocument();
  expect(posts).toHaveLength(3);
  expect(posts[0].key).toBeTruthy();
  expect(posts.every((post) => post.key === posts[0].key && post.text === posts[0].text)).toBe(true);
});

test("проверяет длину по Unicode-символам и запрещает пустое сообщение", async () => {
  open("/chat", fixtureFetch({ chat_messages_list: "no_messages" }));
  await screen.findByText(/Задай первый вопрос/);
  typeMessage("   ");
  expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
  typeMessage("🙂".repeat(4000));
  expect(screen.getByRole("button", { name: "Отправить" })).toBeEnabled();
  typeMessage("🙂".repeat(4001));
  expect(screen.getByRole("textbox", { name: "Сообщение" })).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
});

test("источник открывает цитируемый фрагмент через core-api и позволяет прочитать остальные разделы", async () => {
  const transport = vi.fn(fixtureFetch());
  open("/chat", transport);
  fireEvent.click(await screen.findByRole("link", { name: /Как оформить отгул или отпуск/ }));
  expect(await screen.findByRole("heading", { name: "Отгул" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Отпуск" })).not.toBeInTheDocument();
  const requests = transport.mock.calls.map(([request]) => request)
    .filter((request) => new URL(request.url).pathname === "/api/knowledge/documents/kb_absence_rules");
  expect(requests.at(-1)?.headers.get("Authorization")).toBe("Bearer jwt-anna");
  expect(requests.at(-1)?.cache).toBe("no-store");
  fireEvent.click(screen.getByRole("link", { name: "Весь документ" }));
  expect(await screen.findByRole("heading", { name: "Отпуск" })).toBeInTheDocument();
});

test.each([
  ["other_team_document", "У вас нет доступа к этому документу."],
  ["missing_document", "Документ не найден."],
])("показывает безопасную ошибку документа (%s)", async (fixture, message) => {
  open("/chat/sources/kb_absence_rules/day-off", fixtureFetch({ knowledge_document_get: fixture }));
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Вернуться в чат" })).toHaveAttribute("href", "/chat");
});

test("заголовки внутри блока кода остаются текстом, а отсутствующий раздел открывает текущую версию", async () => {
  const text = ["# Инструкция", "## Первый {#one}", "Текст", "```md", "## Пример {#fake}", "```", "## Второй {#two}", "Конец"].join("\n");
  const { sections } = splitDocument(text);
  expect(sections.map(({ anchor }) => anchor)).toEqual(["one", "two"]);
  expect(sections[0].lines).toContain("## Пример {#fake}");
  open("/chat/sources/kb_absence_rules/old-anchor");
  expect(await screen.findByText(/Цитируемого раздела больше нет/)).toHaveAttribute("role", "status");
  expect(screen.getByRole("heading", { name: "Отпуск" })).toBeInTheDocument();
});

test("Markdown форматирует текст без выполнения HTML, небезопасных ссылок и загрузки изображений", () => {
  render(<Markdown text={'**Важно** [Открыть](https://example.com/help) [Другой адрес](javascript:alert%281%29) [Относительный](/api/private)\n\n<img src="https://example.com/html">\n\n![Картинка](https://example.com/image)'} />);
  expect(screen.getByText("Важно").tagName).toBe("STRONG");
  expect(screen.getByRole("link", { name: "Открыть" })).toHaveAttribute("href", "https://example.com/help");
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
