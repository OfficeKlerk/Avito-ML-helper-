// @vitest-environment node
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, call, createApi, newIdempotencyKey } from "./client";
import { fixtureFetch } from "./fixtures";

const BASE = "http://core-api.test";

function recording(transport: (r: Request) => Promise<Response>) {
  const seen: Request[] = [];
  return { seen, fetch: (r: Request) => (seen.push(r.clone()), transport(r)) };
}

afterEach(() => vi.useRealTimers());

test("id запросов и ключи без crypto.randomUUID: на http://<IP> его нет", async () => {
  vi.stubGlobal("crypto", { getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto) });
  try {
    expect(newIdempotencyKey()).toMatch(/^[0-9a-f]{32}$/);
    const t = recording(fixtureFetch());
    await call(createApi({ baseUrl: BASE, getToken: () => "t", fetch: t.fetch }).GET("/api/me"));
    expect(t.seen[0].headers.get("X-Request-Id")).toMatch(/^[0-9a-f]{32}$/);
  } finally {
    vi.unstubAllGlobals();
  }
});

test("GET с токеном: заголовки и типизированный ответ", async () => {
  const t = recording(fixtureFetch());
  const api = createApi({ baseUrl: BASE, getToken: () => "jwt-anna", fetch: t.fetch });
  const me = await call(api.GET("/api/me"));
  expect(me.login).toBe("intern_anna");
  expect(t.seen[0].headers.get("Authorization")).toBe("Bearer jwt-anna");
  expect(t.seen[0].headers.get("X-Request-Id")).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
});

test("401 с токеном закрывает сессию, 401 при входе — нет", async () => {
  const onUnauthorized = vi.fn();
  const anonymous = createApi({ baseUrl: BASE, getToken: () => null, onUnauthorized, fetch: fixtureFetch({ auth_login: "wrong_password" }) });
  const wrong = call(anonymous.POST("/api/auth/login", { body: { login: "intern_anna", password: "x" } }));
  await expect(wrong).rejects.toMatchObject({ status: 401, code: "unauthorized" });
  expect(onUnauthorized).not.toHaveBeenCalled();

  const expired = createApi({ baseUrl: BASE, getToken: () => "old", onUnauthorized, fetch: fixtureFetch({ me: "no_token" }) });
  await expect(call(expired.GET("/api/me"))).rejects.toBeInstanceOf(ApiError);
  expect(onUnauthorized).toHaveBeenCalledOnce();
});

test("текст ошибки берётся с сервера, код — из ответа", async () => {
  const api = createApi({ baseUrl: BASE, getToken: () => "t", fetch: fixtureFetch({ action_confirm: "already_cancelled" }) });
  const error = await call(api.POST("/api/actions/{action_id}/confirm", {
    params: { path: { action_id: "act_1" }, header: { "Idempotency-Key": newIdempotencyKey() } },
  })).catch((e) => e);
  expect(error).toMatchObject({ status: 409, code: "conflict" });
  expect(error.message.length).toBeGreaterThan(0);
});

test("GET повторяется после 503, мутация — нет, ключ идемпотентности уходит как есть", async () => {
  vi.useFakeTimers();
  const answers = [503, 503, 200];
  const flaky = recording(async () => Response.json({ items: [] }, { status: answers.shift()! }));
  const api = createApi({ baseUrl: BASE, getToken: () => "t", fetch: flaky.fetch });
  const list = call(api.GET("/api/actions"));
  await vi.runAllTimersAsync();
  await expect(list).resolves.toEqual({ items: [] });
  expect(flaky.seen).toHaveLength(3);

  const down = recording(async () => Response.json({ error: { code: "unavailable", message: "Сервис заявок недоступен." } }, { status: 503 }));
  const once = createApi({ baseUrl: BASE, getToken: () => "t", fetch: down.fetch });
  const key = newIdempotencyKey();
  const confirm = call(once.POST("/api/actions/{action_id}/confirm", { params: { path: { action_id: "act_1" }, header: { "Idempotency-Key": key } } }));
  await expect(confirm).rejects.toMatchObject({ status: 503, code: "unavailable", message: "Сервис заявок недоступен." });

  const proxy = createApi({ baseUrl: BASE, getToken: () => "t", fetch: async () => new Response("<html>502</html>", { status: 502 }) });
  await expect(call(proxy.POST("/api/chat/messages", { body: { text: "Привет" } }))).rejects.toMatchObject({ code: "unavailable", message: expect.stringMatching(/недоступен/) });
  expect(down.seen).toHaveLength(1);
  expect(down.seen[0].headers.get("Idempotency-Key")).toBe(key);
});

test("сеть недоступна: GET пробует трижды и даёт понятную ошибку", async () => {
  vi.useFakeTimers();
  const broken = recording(async () => { throw new TypeError("fetch failed"); });
  const api = createApi({ baseUrl: BASE, getToken: () => "t", fetch: broken.fetch });
  const me = call(api.GET("/api/me"));
  const checked = expect(me).rejects.toMatchObject({ status: 0, code: "network" });
  await vi.runAllTimersAsync();
  await checked;
  expect(broken.seen).toHaveLength(3);
});

test("таймаут даёт ApiError, отмена вызывающим — AbortError", async () => {
  vi.useFakeTimers();
  let started = () => {};
  const begun = new Promise<void>((resolve) => (started = resolve));
  const hanging = (r: Request) => {
    started();
    // Как настоящий fetch: уже отменённый запрос падает сразу.
    if (r.signal.aborted) return Promise.reject(r.signal.reason);
    return new Promise<Response>((_, reject) => r.signal.addEventListener("abort", () => reject(r.signal.reason)));
  };
  const api = createApi({ baseUrl: BASE, getToken: () => "t", fetch: hanging });
  const slow = call(api.POST("/api/chat/messages", { body: { text: "Привет" } }));
  const checked = expect(slow).rejects.toMatchObject({ code: "timeout" });
  await begun; // таймер ставится до вызова транспорта
  await vi.advanceTimersByTimeAsync(60_000);
  await checked;

  const controller = new AbortController();
  const cancelled = call(api.GET("/api/me", { signal: controller.signal }));
  controller.abort();
  await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
});
