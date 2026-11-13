import createClient from "openapi-fetch";
import { apiBaseUrl } from "../config";
import type { components, paths } from "./schema";

// Типы ответов генерируются из contracts/a_core_api.yaml: npm run gen:api.
export type Schemas = components["schemas"];
export type ApiErrorCode = Schemas["ErrorCode"] | "network" | "timeout";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ApiErrorCode,
    message: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const READ_TIMEOUT_MS = 15_000;
// Сообщение в чат ждёт агента: модель до 25 с плюс вызовы инструментов.
const WRITE_TIMEOUT_MS = 60_000;
// Повторяем только GET: мутации сами не дублируем, для них — Idempotency-Key.
const READ_RETRY_DELAYS_MS = [300, 1000];
const RETRY_STATUSES = new Set([502, 503, 504]);

const CODE_BY_STATUS: Record<number, Schemas["ErrorCode"]> = {
  401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
  422: "validation", 429: "rate_limited", 502: "unavailable", 503: "unavailable", 504: "unavailable",
};

// crypto.randomUUID есть только на HTTPS и localhost; getRandomValues работает и на http://<IP>.
const randomId = (): string => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");

export const newIdempotencyKey = randomId;

type ApiOptions = {
  getToken: () => string | null;
  /** Сервер отклонил токен: сессию нужно закрыть. */
  onUnauthorized?: () => void;
  baseUrl?: string;
  /** Транспорт; в тестах — fixtureFetch. */
  fetch?: (request: Request) => Promise<Response>;
};

export function createApi({ getToken, onUnauthorized, baseUrl = apiBaseUrl, fetch: transport = (r) => fetch(r) }: ApiOptions) {
  const client = createClient<paths>({ baseUrl, fetch: (request: Request) => send(transport, request) });
  client.use({
    onRequest({ request }) {
      const token = getToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      request.headers.set("X-Request-Id", randomId());
      return request;
    },
    onResponse({ request, response }) {
      // 401 без токена — это неверный пароль при входе, а не конец сессии.
      if (response.status === 401 && request.headers.has("Authorization")) onUnauthorized?.();
    },
  });
  return client;
}

export type Api = ReturnType<typeof createApi>;

/** Данные успешного ответа или ApiError с текстом для пользователя. */
export async function call<T>(pending: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await pending;
  if (response.ok) return data as T;
  const body = (error as Partial<Schemas["ErrorResponse"]> | undefined)?.error;
  const code = body?.code ?? CODE_BY_STATUS[response.status] ?? "internal";
  throw new ApiError(
    response.status,
    code,
    body?.message ?? (code === "unavailable" ? "Сервис временно недоступен. Попробуй чуть позже." : "Что-то пошло не так. Попробуй ещё раз."),
    response.headers.get("X-Request-Id") ?? undefined,
  );
}

async function send(transport: (request: Request) => Promise<Response>, request: Request): Promise<Response> {
  const isRead = request.method === "GET";
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), isRead ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, timeout.signal]);
  try {
    for (let attempt = 0; ; attempt++) {
      const canRetry = isRead && attempt < READ_RETRY_DELAYS_MS.length;
      try {
        const response = await transport(new Request(request, { signal }));
        if (!canRetry || !RETRY_STATUSES.has(response.status)) return response;
      } catch (error) {
        if (!canRetry || signal.aborted) throw error;
      }
      await sleep(READ_RETRY_DELAYS_MS[attempt], signal);
    }
  } catch (error) {
    if (request.signal.aborted) throw error; // отменил сам вызывающий, например ушли со страницы
    if (timeout.signal.aborted) throw new ApiError(0, "timeout", "Сервер долго не отвечает. Попробуй ещё раз.");
    throw new ApiError(0, "network", "Нет связи с сервером. Проверь сеть и попробуй ещё раз.");
  } finally {
    clearTimeout(timer);
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason);
    }, { once: true });
  });
}
