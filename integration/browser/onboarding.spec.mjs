import { expect, test } from "@playwright/test";

const question = "Во сколько у нас стендап?";
const sourceTitle = "Ритуалы команды Авито Доставка";
const sourcePath = "/chat/sources/kb_delivery_rituals/standup";
const taskPath = "/onboarding/tasks/t_join_channels";

function chatResponse(page, method) {
  return page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/chat/messages" &&
    response.request().method() === method,
  );
}

async function signIn(page, login, team) {
  await page.goto("/");
  await page.getByLabel("Логин").fill(login);
  await page.getByLabel("Пароль").fill("buddy2026");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("main").getByText(team, { exact: true })).toBeVisible();
}

test("I2: адаптация, ответ с источником и изоляция двух команд", async ({ page }) => {
  const main = page.getByRole("main");
  const history = page.getByRole("list", { name: "История диалога" });
  const messages = history.getByText(question, { exact: true });
  let savedMessageIds;

  await test.step("Анна входит и видит план адаптации", async () => {
    await signIn(page, "intern_anna", "Авито Доставка");
    await page.getByRole("link", { name: "Адаптация", exact: true }).click();
    const nextSteps = page.getByRole("region", { name: "Что сделать дальше" });
    await expect(nextSteps.getByRole("listitem").first()).toBeVisible();
    await expect(nextSteps.getByRole("listitem").first().locator("p")).toHaveText(/\S/);
    await page.goto(taskPath);
    await expect(main.getByText("В работе", { exact: true })).toBeVisible();
  });

  await test.step("Анна задаёт вопрос и открывает цитируемый раздел", async () => {
    await page.getByRole("link", { name: "Чат", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Сообщение" })).toBeVisible();
    await page.getByRole("textbox", { name: "Сообщение" }).fill(question);
    const [response] = await Promise.all([
      chatResponse(page, "POST"),
      page.getByRole("button", { name: "Отправить", exact: true }).click(),
    ]);
    expect(response.ok()).toBe(true);
    const turn = await response.json();
    savedMessageIds = [turn.user_message.id, turn.assistant_message.id];
    expect(savedMessageIds).toEqual([expect.any(String), expect.any(String)]);
    expect(turn.assistant_message.status).toBe("ok");
    expect(turn.assistant_message.sources).toEqual(expect.arrayContaining([
      expect.objectContaining({ doc_id: "kb_delivery_rituals", chunk_id: "kb_delivery_rituals#standup" }),
    ]));
    await expect(messages.last()).toBeVisible();
    const source = history.getByRole("link", { name: new RegExp(sourceTitle) })
      .and(history.locator(`a[href="${sourcePath}"]`)).last();
    await expect(source).toBeVisible();
    await source.click();
    await expect(page.getByRole("heading", { name: sourceTitle, exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Ежедневный стендап" })).toContainText("11:00");
    await expect(page.getByText("Тестовая инструкция, не является регламентом Авито")).toBeVisible();

    await page.getByRole("link", { name: "Вернуться в чат" }).click();
    const [reloaded] = await Promise.all([chatResponse(page, "GET"), page.reload()]);
    expect(reloaded.ok()).toBe(true);
    const { messages: restored } = await reloaded.json();
    expect(restored.map(message => message.id)).toEqual(expect.arrayContaining(savedMessageIds));
    await expect(messages.last()).toBeVisible();
    await expect(source).toBeVisible();
    await expect(history.getByText("11:00", { exact: false }).last()).toBeVisible();
  });

  await test.step("Максим видит свой план и не получает историю или документ Анны", async () => {
    await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
    await signIn(page, "intern_max", "Авто");
    await page.goto(taskPath);
    await expect(main.getByText("Выполнено", { exact: true })).toBeVisible();

    const [loaded] = await Promise.all([
      chatResponse(page, "GET"),
      page.getByRole("link", { name: "Чат", exact: true }).click(),
    ]);
    expect(loaded.ok()).toBe(true);
    const { messages: maxHistory } = await loaded.json();
    const maxIds = new Set(maxHistory.map(message => message.id));
    for (const id of savedMessageIds) {
      expect(maxIds.has(id)).toBe(false);
    }
    await expect(page.getByText("Загружаем историю…")).toHaveCount(0);
    await expect(history.locator(`a[href="${sourcePath}"]`)).toHaveCount(0);

    await page.goto(sourcePath);
    await expect(page.getByText("У вас нет доступа к этому документу.")).toBeVisible();
    await expect(page.getByRole("heading", { name: sourceTitle, exact: true })).toHaveCount(0);
  });
});
