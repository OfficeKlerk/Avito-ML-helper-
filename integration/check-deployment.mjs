import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { appendFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const rollbackRef = process.argv[2] || "76f8a461017b901eecbc6245441e4c1ca6a3df65";
const project = `ai-buddy-d6-${randomUUID().slice(0, 8)}`;
const port = process.env.D6_WEB_PORT || "13056";
const env = {
  ...process.env, WEB_PORT: port, COMPOSE_PROFILES: "", LLM_PROVIDER: "mock",
  LLM_BASE_URL: "", LLM_API_KEY: "", LLM_MODEL: "", CORP_FAULT_TOKEN: "",
  POSTGRES_USER: "buddy", POSTGRES_PASSWORD: "buddy", POSTGRES_DB: "buddy",
  JWT_SECRET: "d6-local-check-secret-32-bytes-min", PUBLIC_RATE_LIMIT: "on",
  CORE_AGENT_URL: "", CORE_CORP_MOCK_URL: "", CORE_KNOWLEDGE_URL: "",
  AGENT_KNOWLEDGE_URL: "", AGENT_MCP_URL: "", WEB_CORE_API_URL: "",
};
const composeArgs = [
  "compose", "--project-name", project, "--env-file", process.platform === "win32" ? "NUL" : "/dev/null",
  "-f", "docker-compose.yml",
];

function command(program, args, cwd = root, capture = false) {
  const result = spawnSync(program, args, { cwd, env, encoding: "utf8", stdio: capture ? "pipe" : "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${program} ${args.slice(0, 2).join(" ")} завершился с кодом ${result.status}${capture ? `\n${result.stderr}` : ""}`);
  }
  return (result.stdout ?? "").trim();
}

const candidate = command("git", ["rev-parse", "HEAD"], root, true);
const rollback = command("git", ["rev-parse", "--verify", `${rollbackRef}^{commit}`], root, true);
assert.notEqual(candidate, rollback, "Выбери другую версию для отката");
command("git", ["merge-base", "--is-ancestor", rollback, candidate]);
const reports = join(root, "reports", "d6", project);
mkdirSync(reports, { recursive: true });
const report = join(reports, "deployment.log");
function record(line) {
  console.log(line);
  appendFileSync(report, `${line}\n`);
}

const scratch = mkdtempSync(join(reports, "checkout-"));
const current = join(scratch, "current");
const previous = join(scratch, "previous");
const worktrees = [];
let activeTree;
let token;

function compose(tree, args, capture = false) {
  return command("docker", [...composeArgs, ...args], tree, capture);
}

function up(tree, sha, phase, build = true) {
  activeTree = tree;
  record(`\n${phase}: ${sha}`);
  compose(tree, ["up", "-d", "--wait", "--wait-timeout", "180", ...(build ? ["--build"] : [])]);
  record(compose(tree, ["images", "--format", "json"], true));
}

function down(tree) {
  compose(tree, ["down"]);
}

function request(path, { body, key, auth = true } = {}) {
  const headers = {};
  if (key) headers["Idempotency-Key"] = key;
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";
  return fetch(`http://127.0.0.1:${port}${path}`, {
    method: body || key ? "POST" : "GET", headers, body: body && JSON.stringify(body),
    signal: AbortSignal.timeout(60_000), redirect: "error",
  });
}

async function json(path, options) {
  const response = await request(path, options);
  assert.equal(response.status, 200, `${path}: HTTP ${response.status}`);
  assert.ok(response.headers.get("X-Request-Id"), `${path}: отсутствует X-Request-Id`);
  return response.json();
}

async function login() {
  ({ token } = await json("/api/auth/login", { body: { login: "intern_anna", password: "buddy2026" }, auth: false }));
  assert.ok(token);
  assert.equal((await json("/api/me")).id, "u_anna");
}

async function checkWeb() {
  const deepLink = await request("/onboarding", { auth: false });
  assert.equal(deepLink.status, 200);
  const asset = (await deepLink.text()).match(/<script[^>]+src="(\/assets\/[^\"]+)"/)?.[1];
  assert.ok(asset, "Нет production-скрипта на прямом маршруте SPA");
  const script = await request(asset, { auth: false });
  assert.equal(script.status, 200);
  await script.body.cancel();
  const missing = await request("/assets/d6-missing.js", { auth: false });
  assert.equal(missing.status, 404);
  await missing.body.cancel();
}

const chat = "/api/chat/messages";
const message = "Запроси доступ к GitLab";
const key = randomUUID();

async function snapshot(action) {
  const saved = await json(`/api/actions/${action}`);
  assert.equal(saved.status, "submitted");
  assert.ok(saved.external_id);
  assert.ok(saved.result?.external_ref);
  const { messages } = await json(chat);
  assert.equal(messages.filter(item => item.role === "user" && item.text === message).length, 1);
  assert.equal(messages.flatMap(item => item.actions).filter(card => card.id === action).length, 1);
  const { items } = await json("/api/notifications");
  const linked = items.filter(item => item.action_id === action && item.kind === "action_status");
  assert.equal(linked.length, 1);
  return {
    id: saved.id, status: saved.status, externalId: saved.external_id, number: saved.result.external_ref,
    messages: messages.map(item => item.id), notification: linked[0].id,
  };
}

async function checkLimits(path, burst) {
  for (let i = 0; i < burst + 3; i++) {
    const response = await request(path, { body: {}, auth: false });
    if (response.status === 429) {
      assert.equal(response.headers.get("Retry-After"), "10");
      assert.ok(response.headers.get("X-Request-Id"));
      assert.equal((await response.json()).error.code, "rate_limited");
      return;
    }
    assert.ok([401, 422].includes(response.status));
    await response.body.cancel();
  }
  assert.fail(`Ограничение частоты для ${path} не сработало`);
}

try {
  record(`Проект ${project}, порт ${port}`);
  record(command("docker", ["compose", "version"], root, true));
  for (const [tree, sha] of [[current, candidate], [previous, rollback]]) {
    command("git", ["-c", "core.autocrlf=false", "worktree", "add", "--detach", tree, sha]);
    worktrees.push(tree);
  }

  up(current, candidate, "Чистый запуск");
  await checkWeb();
  await login();
  const draft = await json(chat, { body: { text: message }, key: randomUUID() });
  assert.equal(draft.assistant_message.actions.length, 1);
  const action = draft.assistant_message.actions[0].id;
  const confirmPath = `/api/actions/${action}/confirm`;
  const sent = await json(confirmPath, { key });
  const initial = await snapshot(action);
  assert.equal(initial.number, sent.result?.external_ref);
  record(`Заявка ${initial.number}, сообщений ${initial.messages.length}, одно уведомление`);

  down(current);
  up(current, candidate, "Повторный запуск", false);
  await login();
  assert.deepEqual(await snapshot(action), initial);

  down(current);
  up(previous, rollback, "Откат на том же томе");
  await checkWeb();
  await login();
  assert.deepEqual(await snapshot(action), initial);

  down(previous);
  up(current, candidate, "Возврат к новой версии");
  await login();
  const replay = await json(confirmPath, { key });
  assert.equal(replay.result?.external_ref, initial.number);
  assert.deepEqual(await snapshot(action), initial);
  await checkLimits("/api/auth/login", 10);
  await checkLimits(chat, 3);
  record("Заявка, история и уведомление сохранены без дублей. Ограничения частоты возвращают HTTP 429.");
} catch (error) {
  record(error.stack);
  process.exitCode = 1;
  if (activeTree) {
    try {
      appendFileSync(report, `${compose(activeTree, ["logs", "--no-color", "--tail", "100"], true)}\n`);
    } catch (logError) {
      record(logError.message);
    }
  }
} finally {
  try {
    if (activeTree) compose(activeTree, ["down", "--volumes", "--remove-orphans"]);
  } catch (error) {
    record(error.message);
    process.exitCode = 1;
  }
  for (const tree of worktrees) {
    try {
      command("git", ["worktree", "remove", "--force", tree]);
    } catch (error) {
      record(error.message);
      process.exitCode = 1;
    }
  }
  rmSync(scratch, { recursive: true, force: true });
  console.log(`Отчёт: ${report}`);
}
