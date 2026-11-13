import { execFileSync } from "node:child_process";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const root = fileURLToPath(new URL("../../", import.meta.url));
const project = process.env.I34_PROJECT;
const corp = process.env.I34_CORP_URL;
const accessTask = "/onboarding/tasks/t_team_space";

async function json(response, status = 200) {
  expect(response.status(), response.url()).toBe(status);
  return response.json();
}

async function signIn(page, login) {
  await page.goto("/login");
  await page.getByLabel("Логин").fill(login);
  await page.getByLabel("Пароль").fill("buddy2026");
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/login"),
    page.getByRole("button", { name: "Войти", exact: true }).click(),
  ]);
  return auth((await json(response)).token);
}

function auth(token) {
  expect(token).toEqual(expect.any(String));
  return { Authorization: `Bearer ${token}` };
}

async function ask(page, text) {
  const message = page.getByRole("textbox", { name: "Сообщение" });
  await message.fill(text);
  const [response] = await Promise.all([
    page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/chat/messages" && response.request().method() === "POST"),
    page.getByRole("button", { name: "Отправить", exact: true }).click(),
  ]);
  const { assistant_message: reply } = await json(response);
  expect(reply.status).toBe("ok");
  return reply;
}

async function draft(page, question, type) {
  const reply = await ask(page, question);
  expect(reply.actions).toHaveLength(1);
  expect(reply.actions[0]).toMatchObject({ type, status: "draft" });
  return reply.actions[0];
}

function actionCard(page, action) {
  return page.getByRole("article").filter({ hasText: action.external_id });
}

function submitDialog(page, action) {
  return Promise.all([
    page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/actions/${action.id}/confirm` &&
      response.request().method() === "POST"),
    page.getByRole("dialog", { name: "Отправить заявку?" }).getByRole("button", { name: "Отправить", exact: true }).click(),
  ]).then(([response]) => response);
}

async function confirm(page, action) {
  const card = actionCard(page, action);
  await expect(card.getByText("Черновик", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Отправить на согласование" }).click();
  const response = await submitDialog(page, action);
  const submitted = await json(response);
  expect(submitted).toMatchObject({ id: action.id, external_id: action.external_id, status: "submitted" });
  await expect(card.getByText("На согласовании", { exact: true })).toBeVisible();
  return { submitted, key: await response.request().headerValue("Idempotency-Key") };
}

function businessDate(daysAhead) {
  const today = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
  const day = new Date(`${today}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + daysAhead);
  while (day.getUTCDay() === 0 || day.getUTCDay() === 6) day.setUTCDate(day.getUTCDate() + 1);
  return new Intl.DateTimeFormat("ru-RU", { timeZone: "UTC", day: "numeric", month: "long" }).format(day);
}

async function manager(request) {
  const response = await request.post("/api/auth/login", {
    data: { login: "lead_olga", password: "buddy2026" },
  });
  return auth((await json(response)).token);
}

function corporateRequest(action) {
  expect(action.external_id).toEqual(expect.any(String));
  return `${corp}/api/v1/requests/${encodeURIComponent(action.external_id)}`;
}

function restartRequestServices() {
  execFileSync("docker", ["restart", `${project}-corp-mock-1`, `${project}-core-api-1`],
    { cwd: root, timeout: 45_000, stdio: "inherit" });
}

test.describe.configure({ timeout: 150_000 });
test.beforeEach(() => {
  expect(project, "Запустите npm run test:requests").toMatch(/^ai-buddy-i34-[a-f0-9]{8}$/);
});

test("I3: отгул, повтор после перезапуска, отказ и отмена", async ({ page, request }) => {
  const headers = await signIn(page, "intern_anna");
  await page.getByRole("link", { name: "Чат", exact: true }).click();
  const clarification = await ask(page, "Хочу взять отгул");
  expect(clarification.text).toContain("На какую дату");
  expect(clarification.actions).toEqual([]);
  const date = businessDate(3);
  const dayOff = await draft(page, date, "absence_request");
  const remote = corporateRequest(dayOff);
  expect(await json(await request.get(remote, { headers }))).toMatchObject({ status: "draft" });

  const { submitted, key } = await confirm(page, dayOff);
  const number = submitted.result.external_ref;
  expect(number).toMatch(/^ABS-/);
  expect(await json(await request.get(remote, { headers }))).toMatchObject({
    status: "submitted", external_ref: number,
  });

  restartRequestServices();
  await expect.poll(async () => (await request.get(remote, { headers })).status(), { timeout: 30_000 }).toBe(200);
  await expect.poll(async () => (await request.get("/api/me", { headers })).status(), { timeout: 30_000 }).toBe(200);
  expect(key).toEqual(expect.any(String));
  const replay = await json(await request.post(`/api/actions/${dayOff.id}/confirm`, {
    headers: { ...headers, "Idempotency-Key": key },
  }));
  expect(replay).toMatchObject({ id: dayOff.id, external_id: dayOff.external_id, result: { external_ref: number } });
  const { actions } = await json(await request.get("/api/actions", { headers }));
  expect(actions.filter(action => action.type === "absence_request" && action.title === dayOff.title))
    .toEqual([expect.objectContaining({ id: dayOff.id, external_id: dayOff.external_id })]);
  await page.reload();
  const history = page.getByRole("list", { name: "История диалога" });
  await expect(history.getByText(date, { exact: true })).toBeVisible();
  await expect(actionCard(page, dayOff).getByText("На согласовании", { exact: true })).toBeVisible();
  await page.goto(`/actions/${dayOff.id}`);
  await expect(actionCard(page, dayOff).getByText(number, { exact: true })).toBeVisible();

  const lead = await manager(request);
  expect(await json(await request.post(`${remote}/reject`, { headers: lead }))).toMatchObject({ status: "rejected" });
  await page.reload();
  await expect(actionCard(page, dayOff).getByText("Отклонена", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Чат", exact: true }).click();
  const second = await draft(page, `Хочу взять отгул ${businessDate(9)}`, "absence_request");
  await confirm(page, second);
  await actionCard(page, second).getByRole("button", { name: "Отменить заявку", exact: true }).click();
  await page.getByRole("dialog", { name: "Отменить заявку?" }).getByRole("button", { name: "Отменить заявку", exact: true }).click();
  await expect(actionCard(page, second).getByText("Отменена", { exact: true })).toBeVisible();
  expect(await json(await request.get(corporateRequest(second), { headers }))).toMatchObject({ status: "cancelled" });
});

test("I4: выдача доступа, связанная задача и ограничения", async ({ page, request }) => {
  const headers = await signIn(page, "intern_anna");
  await page.goto(accessTask);
  await expect(page.getByRole("main").getByText("К выполнению", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Спросить в чате" }).click();
  await expect(page.getByRole("textbox", { name: "Сообщение" })).toHaveValue(/пространство команды/);
  const action = await draft(page, "Запроси доступ в пространство команды", "access_request");
  const remote = corporateRequest(action);
  expect(await json(await request.get(remote, { headers }))).toMatchObject({
    status: "draft", payload: { system: "team_space" },
  });
  await confirm(page, action);
  expect(await json(await request.get(remote, { headers }))).toMatchObject({
    status: "submitted", fulfilled_at: null,
  });
  await page.goto(accessTask);
  await expect(page.getByRole("main").getByText("В работе", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Связанная заявка" })).toHaveAttribute("href", new RegExp(`/actions/${action.id}`));

  await page.getByRole("link", { name: "Чат", exact: true }).click();
  const pending = await ask(page, "Запроси доступ в пространство команды");
  expect(pending.text).toContain("ждёт согласования");
  expect(pending.actions).toEqual([]);
  expect((await request.post(`${remote}/approve`, { headers })).status()).toBe(403);

  const lead = await manager(request);
  const granted = await json(await request.post(`${remote}/approve`, { headers: lead }));
  expect(granted).toMatchObject({ status: "approved", fulfilled_at: expect.any(String) });
  await page.goto(accessTask);
  await expect(page.getByRole("main").getByText("Выполнено", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Связанная заявка" }).click();
  await expect(actionCard(page, action).getByText("Доступ выдан", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Чат", exact: true }).click();
  const alreadyGranted = await ask(page, "Запроси доступ в пространство команды");
  expect(alreadyGranted.text).toContain("у тебя уже есть");
  expect(alreadyGranted.actions).toEqual([]);
  const { actions } = await json(await request.get("/api/actions", { headers }));
  expect(actions.filter(card => card.type === "access_request" && card.fields["Система"] === action.fields["Система"]))
    .toEqual([expect.objectContaining({ id: action.id, status: "approved" })]);

  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  const other = await signIn(page, "intern_max");
  await page.getByRole("link", { name: "Чат", exact: true }).click();
  const denied = await ask(page, "Запроси доступ к VPN");
  expect(denied.text).toContain("не предусмотрен для твоей команды");
  expect(denied.actions).toEqual([]);
  expect((await request.get(remote, { headers: other })).status()).toBe(403);
});

test("I5: реальная модель, отгул и выдача доступа", async ({ page, request }, testInfo) => {
  const model = process.env.I5_LIVE_MODEL;
  expect(model, "Запустите npm run test:model").toBeTruthy();
  const headers = await signIn(page, "intern_anna");
  const lead = await manager(request);
  const outcomes = [];

  async function completeDraft(action, expectedPayload, elapsedMs) {
    const remote = corporateRequest(action);
    expect(await json(await request.get(remote, { headers }))).toMatchObject({
      status: "draft", payload: expectedPayload,
    });
    const { submitted } = await confirm(page, action);
    expect(submitted.result.external_ref).toEqual(expect.any(String));
    const approved = await json(await request.post(`${remote}/approve`, { headers: lead }));
    expect(approved).toMatchObject({ status: "approved" });
    outcomes.push({ type: action.type, assistantStatus: "ok", elapsedMs, requestStatus: approved.status });
    return approved;
  }

  try {
    await page.getByRole("link", { name: "Чат", exact: true }).click();
    const clarification = await ask(page, "Хочу взять отгул. Как его оформить?");
    expect(clarification.text).toMatch(/дат|когда|день/i);
    expect(clarification.actions).toEqual([]);
    const date = businessDate(4);
    const started = performance.now();
    const absence = await draft(page, `Подготовь черновик заявки на отгул на ${date}`, "absence_request");
    const payload = (await json(await request.get(corporateRequest(absence), { headers }))).payload;
    const shownDate = new Intl.DateTimeFormat("ru-RU", { timeZone: "UTC", day: "numeric", month: "long" })
      .format(new Date(`${payload.date_from}T00:00:00Z`));
    expect(shownDate).toBe(date);
    await completeDraft(absence, { kind: "day_off", date_to: payload.date_from }, Math.round(performance.now() - started));
    await page.goto(`/actions/${absence.id}`);
    await expect(actionCard(page, absence).getByText("Согласована", { exact: true })).toBeVisible();

    await page.goto(accessTask);
    await page.getByRole("link", { name: "Спросить в чате" }).click();
    const startedAccess = performance.now();
    const access = await draft(page, "Подготовь черновик заявки на доступ в пространство команды", "access_request");
    const granted = await completeDraft(access, { system: "team_space" }, Math.round(performance.now() - startedAccess));
    expect(granted.fulfilled_at).toEqual(expect.any(String));
    await page.goto(accessTask);
    await expect(page.getByRole("main").getByText("Выполнено", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Связанная заявка" }).click();
    await expect(actionCard(page, access).getByText("Доступ выдан", { exact: true })).toBeVisible();
  } finally {
    await testInfo.attach("live-model", {
      body: JSON.stringify({ model, outcomes }, null, 2), contentType: "application/json",
    });
  }
});

test("I6: отказ, таймаут и потеря ответа при отправке", async ({ page, request }, testInfo) => {
  expect(process.env.I6_RECOVERY, "Запустите npm run test:recovery").toBe("1");
  const token = process.env.CORP_FAULT_TOKEN;
  expect(token).toEqual(expect.any(String));
  const headers = await signIn(page, "intern_anna");
  await page.getByRole("link", { name: "Чат", exact: true }).click();
  const date = businessDate(4);
  const question = `Хочу взять отгул ${date}`;
  const action = await draft(page, question, "absence_request");
  const remote = corporateRequest(action);
  const card = actionCard(page, action);
  const confirmPath = `/api/actions/${action.id}/confirm`;
  const timings = [];

  async function arm(mode, delay) {
    const response = await request.post(`${corp}/test/faults`, {
      headers: { "X-Corp-Fault-Token": token },
      data: { request_id: action.external_id, operation: "submit", mode, delay_ms: delay },
    });
    expect(response.status()).toBe(204);
  }

  async function notifications() {
    const { items } = await json(await request.get("/api/notifications", { headers }));
    return items.filter(item => item.action_id === action.id);
  }

  async function attempt(mode, delay, expectedStatus) {
    await arm(mode, delay);
    const started = performance.now();
    const response = await submitDialog(page, action);
    timings.push({ mode, httpStatus: response.status(), elapsedMs: Math.round(performance.now() - started) });
    return {
      body: await json(response, expectedStatus),
      key: await response.request().headerValue("Idempotency-Key"),
      requestId: await response.headerValue("X-Request-Id"),
    };
  }

  try {
    await expect(card.getByText("Черновик", { exact: true })).toBeVisible();
    await card.getByRole("button", { name: "Отправить на согласование" }).click();
    const dialog = page.getByRole("dialog", { name: "Отправить заявку?" });
    let key;
    for (const [mode, delay] of [["unavailable", undefined], ["delay", 4500]]) {
      const failed = await attempt(mode, delay, 503);
      expect(failed.body.error.code).toBe("unavailable");
      expect(failed.key).toEqual(expect.any(String));
      key ??= failed.key;
      expect(failed.key).toBe(key);
      await expect(dialog.getByText(/Не удалось проверить результат/)).toBeVisible();
      await expect(card.getByText("Черновик", { exact: true })).toBeVisible();
      const stored = await json(await request.get(remote, { headers }));
      expect(stored).toMatchObject({ status: "draft", external_ref: null });
      expect(await notifications()).toEqual([]);
    }
    expect(timings[1].elapsedMs).toBeGreaterThanOrEqual(2500);

    const recovered = await attempt("drop_response", undefined, 200);
    expect(recovered.key).toBe(key);
    const number = recovered.body.result.external_ref;
    expect(number).toMatch(/^ABS-/);
    expect(recovered.body).toMatchObject({ id: action.id, external_id: action.external_id, status: "submitted" });
    await expect(dialog).toHaveCount(0);
    await expect(card.getByText(number, { exact: true })).toBeVisible();
    expect(await json(await request.get(remote, { headers }))).toMatchObject({
      status: "submitted", external_ref: number,
    });
    const beforeRestart = await notifications();
    expect(beforeRestart).toEqual([expect.objectContaining({
      action_id: action.id, kind: "action_status", text: expect.stringContaining("отправлена на согласование"),
    })]);

    restartRequestServices();
    await expect.poll(async () => (await request.get(remote, { headers })).status(), { timeout: 30_000 }).toBe(200);
    await expect.poll(async () => (await request.get("/api/me", { headers })).status(), { timeout: 30_000 }).toBe(200);
    const replay = await json(await request.post(confirmPath, { headers: { ...headers, "Idempotency-Key": key } }));
    expect(replay).toMatchObject({ id: action.id, external_id: action.external_id, result: { external_ref: number } });
    const { actions } = await json(await request.get("/api/actions", { headers }));
    expect(actions.filter(item => item.type === action.type && item.title === action.title))
      .toEqual([expect.objectContaining({ id: action.id, external_id: action.external_id, status: "submitted" })]);
    expect(await notifications()).toEqual(beforeRestart);

    await page.reload();
    await expect(page.getByRole("list", { name: "История диалога" }).getByText(question, { exact: true })).toBeVisible();
    await expect(card.getByText("На согласовании", { exact: true })).toBeVisible();
    await expect(card.getByText(number, { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Уведомления", exact: true }).click();
    await expect(page.getByRole("main").getByText(beforeRestart[0].text, { exact: true })).toHaveCount(1);
    await page.goto(`/actions/${action.id}`);
    await expect(card.getByText(number, { exact: true })).toBeVisible();
    timings.push({ mode: "recovered", requestId: recovered.requestId, status: replay.status });
  } finally {
    await testInfo.attach("recovery", { body: JSON.stringify(timings, null, 2), contentType: "application/json" });
  }
});
