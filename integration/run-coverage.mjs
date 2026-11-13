import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { goLines, coverageReport } from "./coverage-summary.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const project = `ai-buddy-q1-${randomUUID().slice(0, 8)}`;
const output = join(root, "reports", "coverage", project);
const compose = [
  "compose", "--project-name", project,
  "--env-file", process.platform === "win32" ? "NUL" : "/dev/null",
  "-f", "docker-compose.yml",
];
const context = ["contracts", "fixtures", "data"].flatMap(name => ["--build-context", `${name}=./${name}`]);
const postgres = { POSTGRES_USER: "buddy", POSTGRES_PASSWORD: "buddy", POSTGRES_DB: "buddy" };
const env = { ...process.env, ...postgres, COMPOSE_PROFILES: "" };
const reportMount = ["-v", `${output}:/reports`];
const goTest = [
  "go test ./... -count=1 -json -coverpkg=./... -coverprofile=/reports/$1.out > /reports/$1-tests.jsonl",
  'status=$?; if [ "$status" -ne 0 ]; then tail -60 "/reports/$1-tests.jsonl"; exit "$status"; fi',
  'if grep -q \'"Action":"skip","Package":.*"Test":\' "/reports/$1-tests.jsonl"; then',
  'grep \'"Action":"skip","Package":.*"Test":\' "/reports/$1-tests.jsonl"; exit 1; fi',
].join("\n");

function run(args) {
  const result = spawnSync("docker", args, { cwd: root, env, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Docker завершился с кодом ${result.status}: ${args.slice(0, 3).join(" ")}`);
}

function read(name) {
  return JSON.parse(readFileSync(join(output, name), "utf8"));
}

function image(component) {
  return `ai-buddy-q1-${component}:test`;
}

mkdirSync(output, { recursive: true });
try {
  run([...compose, "up", "-d", "--wait", "postgres"]);
  for (const component of ["core-api", "corp-mock", "agent", "knowledge-service", "web-app"]) {
    console.log(`\nПокрытие: ${component}`);
    run(["build", "-q", "--target", "test", ...context, "-t", image(component), `./${component}`]);
    const options = ["run", "--rm", ...reportMount];
    switch (component) {
      case "core-api":
      case "corp-mock": {
        const variable = component === "core-api" ? "CORE_TEST_DATABASE_URL" : "CORP_TEST_DATABASE_URL";
        const database = component.replace("-", "_");
        run([...compose, "exec", "-T", "postgres", "createdb", "-U", postgres.POSTGRES_USER, database]);
        run([...options, "-v", `${join(root, "data")}:/data:ro`, "--network", `${project}_default`,
          "-e", `${variable}=postgres://buddy:buddy@postgres:5432/${database}?sslmode=disable`,
          image(component), "sh", "-c", goTest, "go-coverage", component]);
        break;
      }
      case "agent":
      case "knowledge-service":
        run([...options, image(component), "python", "-m", "pytest", "-p", "no:cacheprovider",
          `--cov-report=json:/reports/${component}.json`]);
        break;
      case "web-app":
        run([...options, image(component), "npm", "test", "--",
          "--coverage.reporter=json-summary", "--coverage.reportsDirectory=/reports/web-app"]);
        break;
    }
  }

  const components = Object.fromEntries(["core-api", "corp-mock"].map(component => [
    component, goLines(readFileSync(join(output, `${component}.out`), "utf8"), join(root, component)),
  ]));
  for (const component of ["agent", "knowledge-service"]) {
    const totals = read(`${component}.json`).totals;
    components[component] = { covered: totals.covered_lines, total: totals.num_statements };
  }
  const { covered, total } = read("web-app/coverage-summary.json").total.lines;
  components["web-app"] = { covered, total };
  const { markdown, passed } = coverageReport(components);
  writeFileSync(join(output, "summary.md"), markdown);
  console.log(`\n${markdown}\n${join(output, "summary.md")}`);
  if (!passed) process.exitCode = 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  try {
    run([...compose, "down", "--volumes"]);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
