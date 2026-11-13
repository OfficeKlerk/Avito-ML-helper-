import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { copyFileSync, cpSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const root = fileURLToPath(new URL("../../", import.meta.url));
const live = process.argv[2] === "model";
const settings = live ? parseEnv(readFileSync(join(root, ".env"), "utf8")) : {};
if (live && ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"].some(name => !settings[name]?.trim())) {
  throw new Error("Для прогона с моделью заполни LLM_BASE_URL, LLM_MODEL и LLM_API_KEY в .env.");
}
const project = `ai-buddy-q2-${randomUUID().slice(0, 8)}`;
const kbDir = join(root, "reports", "q2", project, "kb");
mkdirSync(kbDir, { recursive: true });
cpSync(join(root, "data", "kb"), kbDir, { recursive: true });
copyFileSync(join(root, "integration", "browser", "security", "kb_q2_room.md"), join(kbDir, "kb_q2_room.md"));
const port = process.env.Q2_WEB_PORT ?? "13042";
const corpPort = process.env.Q2_CORP_PORT ?? "13043";
const env = {
  ...process.env,
  WEB_PORT: port, CORP_MOCK_PORT: corpPort, COMPOSE_PROFILES: "",
  Q2_KB_DIR: kbDir,
  JWT_SECRET: randomUUID(), POSTGRES_PASSWORD: randomUUID(), POSTGRES_USER: "buddy", POSTGRES_DB: "buddy",
  CORE_AGENT_URL: "", CORE_CORP_MOCK_URL: "", CORE_KNOWLEDGE_URL: "",
  AGENT_KNOWLEDGE_URL: "", AGENT_MCP_URL: "", WEB_CORE_API_URL: "", CORP_FAULT_TOKEN: "",
  LLM_PROVIDER: live ? "openai" : "mock", LLM_BASE_URL: settings.LLM_BASE_URL ?? "",
  LLM_MODEL: settings.LLM_MODEL ?? "", LLM_API_KEY: settings.LLM_API_KEY ?? randomUUID(),
  LLM_TIMEOUT_SECONDS: "25", LLM_MAX_TOOL_CALLS: "5",
};
const markers = [env.JWT_SECRET, env.POSTGRES_PASSWORD];
if (!live) markers.push(env.LLM_API_KEY);
const compose = [
  "compose", "--progress", "quiet", "--project-name", project,
  "--env-file", process.platform === "win32" ? "NUL" : "/dev/null",
  "-f", "docker-compose.yml", "-f", "integration/browser/requests.compose.yml",
  "-f", "integration/browser/security.compose.yml",
];
const run = (command, args, options = {}) => spawnSync(command, args, {
  cwd: root, env, stdio: "inherit", ...options,
});
let status = 1;
try {
  const started = run("docker", [...compose, "up", "-d", "--build", "--wait"]);
  if (started.status !== 0) throw new Error("Стенд Q2 не запустился.");
  const browserEnv = {
    ...process.env, I2_BASE_URL: `http://127.0.0.1:${port}`, Q2_CORP_URL: `http://127.0.0.1:${corpPort}`,
    Q2_PROJECT: project,
    Q2_SECRET_MARKERS: JSON.stringify(markers),
  };
  delete browserEnv.LLM_API_KEY;
  const checked = run(process.execPath, [
    "integration/browser/node_modules/@playwright/test/cli.js",
    "test", "--config", "integration/browser/playwright.config.mjs",
    "--output", `reports/q2/${live ? "model" : "rules"}`, "security.spec.mjs",
  ], { env: browserEnv });
  status = checked.status ?? 1;
  if (live) {
    const logs = run("docker", [...compose, "logs", "--no-color"], { encoding: "utf8", stdio: "pipe" });
    if (logs.status !== 0 || (logs.stdout + logs.stderr).includes(env.LLM_API_KEY)) {
      console.error("Проверка ключа модели в логах не пройдена.");
      status = 1;
    }
  }
} finally {
  const cleanup = run("docker", [...compose, "down", "--volumes"]);
  process.exitCode = status || (cleanup.status ?? 1);
}
