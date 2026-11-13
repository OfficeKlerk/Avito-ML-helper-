import { cpus, totalmem, version } from "node:os";
import { expect, test } from "@playwright/test";

const mode = process.env.Q3_PERFORMANCE;
const waiting = "Ждём ответа помощника…";

async function signIn(page) {
  await page.goto("/");
  await page.getByLabel("Логин").fill("intern_anna");
  await page.getByLabel("Пароль").fill("buddy2026");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("main").getByText("Авито Доставка", { exact: true })).toBeVisible();
}

async function noOverflow(page) {
  const excess = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(excess, "страница не прокручивается горизонтально").toBeLessThanOrEqual(1);
}

// Измеряем в браузере от события пользователя до кадра после изменения DOM.
// Ожидание Playwright и сетевой запрос в этот интервал не входят.
async function measure(page, event, selector, present, action) {
  await page.evaluate(({ event, selector, present }) => {
    window.q3Measurement = new Promise(resolve => {
      document.addEventListener(event, () => {
        const started = performance.now();
        const frame = () => {
          if (Boolean(document.querySelector(selector)) === present) resolve(performance.now() - started);
          else if (performance.now() - started < 2000) requestAnimationFrame(frame);
          else resolve(2000);
        };
        requestAnimationFrame(frame);
      }, { capture: true, once: true });
    });
  }, { event, selector, present });
  await action();
  return Math.round(await page.evaluate(() => window.q3Measurement));
}

async function chatRequest(page, text) {
  const input = page.getByRole("textbox", { name: "Сообщение" });
  await input.fill(text);
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === "/api/chat/messages" &&
      response.request().method() === "POST"),
    page.getByRole("button", { name: "Отправить", exact: true }).click(),
  ]);
  expect(response.ok()).toBe(true);
  const reply = (await response.json()).assistant_message;
  expect(reply.status).toMatch(mode === "model" ? /^(ok|degraded)$/ : /^ok$/);
  await expect(input).toHaveValue("");
  const { requestStart, responseEnd } = response.request().timing();
  expect(requestStart).toBeGreaterThanOrEqual(0);
  expect(responseEnd).toBeGreaterThan(requestStart);
  return { elapsedMs: Math.round(responseEnd - requestStart), status: reply.status };
}

test.beforeEach(() => {
  expect(mode, "Запустите run-requests.mjs performance или performance-model").toMatch(/^(rules|model)$/);
});

for (const width of [360, 1280]) {
  test(`Q3: отклик интерфейса, клавиатура и чат при ${width} px`, async ({ page, browser }, testInfo) => {
    test.setTimeout(150_000);
    await page.setViewportSize({ width, height: 800 });
    const samples = { openDialogMs: [], closeDialogMs: [], validateMessageMs: [], chatHttp: [] };
    const chatNav = page.getByRole("navigation").getByRole("link", { name: "Чат", exact: true });
    const input = page.getByRole("textbox", { name: "Сообщение" });
    try {
      await signIn(page);
      await page.keyboard.press("Tab");
      const skip = page.getByRole("link", { name: "К содержанию" });
      await expect(skip).toBeFocused();
      expect(await skip.evaluate(element => getComputedStyle(element).outlineStyle)).not.toBe("none");
      await page.keyboard.press("Enter");
      await expect(page.getByRole("main")).toBeFocused();
      await noOverflow(page);

      await page.goto("/actions/act_anna_dayoff_1");
      const trigger = page.getByRole("button", { name: "Отправить на согласование" });
      const dialog = page.getByRole("dialog", { name: "Отправить заявку?" });
      for (let attempt = 0; attempt < 5; attempt++) {
        await trigger.focus();
        samples.openDialogMs.push(await measure(page, "keydown", "dialog[open]", true, () => trigger.press("Enter")));
        await expect(dialog.getByRole("button", { name: "Назад" })).toBeFocused();
        await page.keyboard.press("Tab");
        await expect(dialog.getByRole("button", { name: "Отправить", exact: true })).toBeFocused();
        await noOverflow(page);
        samples.closeDialogMs.push(await measure(page, "keydown", "dialog[open]", false, () => page.keyboard.press("Escape")));
        await expect(trigger).toBeFocused();
      }

      await chatNav.click();
      for (let attempt = 0; attempt < 5; attempt++) {
        await input.fill("Ж".repeat(4000));
        await expect(page.getByRole("button", { name: "Отправить", exact: true })).toBeEnabled();
        await input.press("End");
        samples.validateMessageMs.push(await measure(page, "input",
          "textarea[aria-invalid=true]", true, () => page.keyboard.insertText("Я")));
        await expect(page.getByText("Сократи сообщение до 4000 символов.")).toBeVisible();
        await expect(page.getByRole("button", { name: "Отправить", exact: true })).toBeDisabled();
      }
      for (const question of ["Во сколько у нас стендап?", "Где проходит планирование спринта?", "Как часто встречаться с наставником?"]) {
        const sample = await chatRequest(page, question);
        samples.chatHttp.push(sample);
        if (sample.status === "degraded") {
          await expect(page.getByText("Упрощённый ответ", { exact: true }).last()).toBeVisible();
        }
      }
      expect(samples.chatHttp.some(sample => sample.status === "ok")).toBe(true);
      if (mode === "rules") {
        const marker = `Длинное сообщение ${width}: `;
        const long = marker + "Ж".repeat(3950 - marker.length);
        await chatRequest(page, long);
        await expect(page.getByRole("list", { name: "История диалога" }).getByText(new RegExp(`^${marker}`))).toBeVisible();
        await noOverflow(page);
      }
      for (const name of ["openDialogMs", "closeDialogMs", "validateMessageMs"]) {
        expect(Math.max(...samples[name]), name).toBeLessThan(1000);
      }
    } finally {
      await testInfo.attach("performance", {
        body: JSON.stringify({
          width, height: 800, mode, model: process.env.I5_LIVE_MODEL || null,
          browser: browser.version(), os: version(), cpu: cpus()[0].model,
          logicalCpus: cpus().length, ramGiB: Math.round(totalmem() / 2 ** 30), samples,
        }, null, 2),
        contentType: "application/json",
      });
    }
  });
}

test("Q3: ожидание, доступность навигации и повтор после ошибки", async ({ page }) => {
  test.skip(mode === "model", "Управляемая задержка проверяется на стенде по правилам");
  await page.setViewportSize({ width: 360, height: 800 });
  await signIn(page);
  const nav = page.getByRole("navigation");
  await nav.getByRole("link", { name: "Чат", exact: true }).click();
  let blocked;
  const observed = new Promise(resolve => { blocked = resolve; });
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  const pattern = "**/api/chat/messages";
  const routeHandler = async route => {
    if (route.request().method() !== "POST") return route.continue();
    blocked();
    await hold;
    await route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "Q3: сервис временно недоступен" } } });
  };
  await page.route(pattern, routeHandler);
  const question = "Когда у нас ежедневный стендап? Проверка восстановления Q3.";
  const input = page.getByRole("textbox", { name: "Сообщение" });
  await input.fill(question);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  try {
    await observed;
    await expect(page.locator(".chat-announcement")).toHaveText(waiting);
    await expect(page.getByText(waiting, { exact: true }).filter({ visible: true }).last()).toBeVisible();
    await expect(page.getByRole("button", { name: "Отправляем…" })).toBeDisabled();
    const profile = nav.getByRole("link", { name: "Профиль" });
    await profile.focus();
    await expect(profile).toBeFocused();
    await noOverflow(page);
  } finally {
    release();
  }
  await expect(page.getByRole("alert")).toContainText("Q3: сервис временно недоступен");
  await expect(input).toHaveValue(question);
  await page.unroute(pattern, routeHandler);
  await page.getByRole("button", { name: "Повторить отправку" }).click();
  await expect(page.getByRole("list", { name: "История диалога" }).getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);

  let navigationRequest;
  const waitingForNavigation = new Promise(resolve => { navigationRequest = resolve; });
  let finishNavigationRequest;
  const navigationHold = new Promise(resolve => { finishNavigationRequest = resolve; });
  await page.route(pattern, async route => {
    if (route.request().method() !== "POST") return route.continue();
    navigationRequest();
    await navigationHold;
    await route.abort();
  });
  await input.fill("Что мне делать дальше?");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  try {
    await waitingForNavigation;
    await expect(page.locator(".chat-announcement")).toHaveText(waiting);
    await nav.getByRole("link", { name: "Профиль" }).press("Enter");
    await expect(page.getByRole("main").getByText("Авито Доставка", { exact: true })).toBeVisible();
  } finally {
    finishNavigationRequest();
  }
});
