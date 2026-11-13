import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const project = `ai-buddy-i34-${randomUUID().slice(0, 8)}`;
const env = {
  ...process.env,
  WEB_PORT: process.env.I34_WEB_PORT ?? "13034",
  CORP_MOCK_PORT: process.env.I34_CORP_PORT ?? "13035",
  LLM_PROVIDER: "mock",
  CORE_AGENT_URL: "", CORE_CORP_MOCK_URL: "", CORE_KNOWLEDGE_URL: "",
  AGENT_KNOWLEDGE_URL: "", AGENT_MCP_URL: "", WEB_CORE_API_URL: "",
  COMPOSE_PROFILES: "", CORP_FAULT_TOKEN: "",
  I34_PROJECT: project,
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
    status = run(process.execPath, [
      "integration/browser/node_modules/@playwright/test/cli.js",
      "test", "--config", "integration/browser/playwright.config.mjs", "--workers", "1", "requests.spec.mjs",
    ]);
  }
  if (status !== 0) run("docker", [...compose, "ps", "-a"]);
} finally {
  const cleanup = run("docker", [...compose, "down", "--volumes"]);
  process.exitCode = status || cleanup;
}
