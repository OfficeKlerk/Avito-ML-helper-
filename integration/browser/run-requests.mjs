import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const root = fileURLToPath(new URL("../../", import.meta.url));
const recovery = process.argv[2] === "recovery";
const performanceCheck = ["performance", "performance-model"].includes(process.argv[2]);
const liveModel = ["model", "performance-model"].includes(process.argv[2]);
const settings = liveModel ? parseEnv(readFileSync(join(root, ".env"), "utf8")) : {};
if (liveModel && ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"].some(name => !settings[name]?.trim())) {
  throw new Error("В .env нужны LLM_BASE_URL, LLM_MODEL и LLM_API_KEY для прогона I5.");
}
const project = `ai-buddy-i34-${randomUUID().slice(0, 8)}`;
const env = {
  ...process.env,
  WEB_PORT: process.env.I34_WEB_PORT ?? "13034",
  CORP_MOCK_PORT: process.env.I34_CORP_PORT ?? "13035",
  LLM_PROVIDER: liveModel ? "openai" : "mock",
  LLM_BASE_URL: settings.LLM_BASE_URL ?? "",
  LLM_MODEL: settings.LLM_MODEL ?? "",
  LLM_API_KEY: settings.LLM_API_KEY ?? "",
  LLM_TIMEOUT_SECONDS: settings.LLM_TIMEOUT_SECONDS || "25",
  LLM_MAX_TOOL_CALLS: settings.LLM_MAX_TOOL_CALLS || "5",
  CORE_AGENT_URL: "", CORE_CORP_MOCK_URL: "", CORE_KNOWLEDGE_URL: "",
  AGENT_KNOWLEDGE_URL: "", AGENT_MCP_URL: "", WEB_CORE_API_URL: "",
  COMPOSE_PROFILES: "", CORP_FAULT_TOKEN: recovery ? randomUUID() : "",
  I34_PROJECT: project,
  I6_RECOVERY: recovery ? "1" : "",
  I5_LIVE_MODEL: liveModel ? settings.LLM_MODEL : "",
  Q3_PERFORMANCE: performanceCheck ? (liveModel ? "model" : "rules") : "",
};
env.I2_BASE_URL = `http://127.0.0.1:${env.WEB_PORT}`;
env.I34_CORP_URL = `http://127.0.0.1:${env.CORP_MOCK_PORT}`;

const compose = [
  "compose", "--progress", "quiet", "--project-name", project,
  "--env-file", process.platform === "win32" ? "NUL" : "/dev/null",
  "-f", "docker-compose.yml", "-f", "integration/browser/requests.compose.yml",
];
function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, env, stdio: "inherit" });
  if (result.error) console.error(result.error.message);
  return result.status ?? 1;
}

let status = 1;
try {
  status = run("docker", [...compose, "up", "-d", "--build", "--wait"]);
  if (status === 0) {
    const { LLM_API_KEY: _key, ...browserEnv } = env;
    const args = [
      "integration/browser/node_modules/@playwright/test/cli.js",
      "test", "--config", "integration/browser/playwright.config.mjs", "--workers", "1",
      ...(performanceCheck ? ["performance.spec.mjs"] : [
        recovery || liveModel ? "--grep" : "--grep-invert",
        recovery ? "I6:" : liveModel ? "I5:" : "I[56]:", "requests.spec.mjs",
      ]),
    ];
    const result = spawnSync(process.execPath, args, { cwd: root, env: browserEnv, stdio: "inherit" });
    if (result.error) console.error(result.error.message);
    status = result.status ?? 1;
  }
  if (status !== 0) run("docker", [...compose, "ps", "-a"]);
} finally {
  try {
    if (recovery) {
      const reportDir = join(root, "reports", "i6-recovery", project);
      mkdirSync(reportDir, { recursive: true });
      const logs = spawnSync("docker", [...compose, "logs", "--no-color"], { cwd: root, env, encoding: "utf8" });
      writeFileSync(join(reportDir, "compose.log"), (logs.stdout ?? "") + (logs.stderr ?? ""));
      console.log(`Логи стенда: ${reportDir}`);
      if (logs.status !== 0) status = 1;
    }
  } finally {
    const cleanup = run("docker", [...compose, "down", "--volumes"]);
    process.exitCode = status || cleanup;
  }
}
