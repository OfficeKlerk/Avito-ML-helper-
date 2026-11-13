import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const scenarios = ["onboarding", "knowledge", "absence", "access"];
const events = new Map([
  ["scenario_started", "client"], ["source_opened", "client"], ["human_help_requested", "client"],
  ["assistant_answered", "server"], ["action_confirmed", "server"],
  ["action_succeeded", "server"], ["action_failed", "server"],
]);
const statuses = {
  assistant_answered: ["ok", "degraded", "error"],
  action_confirmed: ["submitted"],
  action_succeeded: ["approved"],
  action_failed: ["rejected", "cancelled"],
};

function groupEvents(rows) {
  if (!Array.isArray(rows)) throw new Error("Ожидается JSON-массив событий.");
  const groups = new Map();
  for (const row of rows) {
    const { run, event_id: id, scenario, event, source, status, action, recorded_at: timestamp } = row;
    const time = Date.parse(timestamp);
    const hasAction = event?.startsWith("action_");
    if (!Number.isSafeInteger(run) || run < 1 || typeof id !== "string" || !id ||
        (scenario !== null && !scenarios.includes(scenario)) ||
        !events.has(event) || events.get(event) !== source || !Number.isFinite(time) ||
        (hasAction ? !Number.isSafeInteger(action) || action < 1 : action !== null) ||
        (statuses[event] ? !statuses[event].includes(status) : status !== null)) {
      throw new Error("Некорректная запись в выгрузке B3.");
    }
    if (!groups.has(run)) groups.set(run, new Map());
    const group = groups.get(run);
    const normalized = { id, scenario, event, status, action, time };
    if (group.has(id) && JSON.stringify(group.get(id)) !== JSON.stringify(normalized)) {
      throw new Error("Один идентификатор события содержит разные данные.");
    }
    group.set(id, normalized);
  }
  return [...groups.values()].map(group => [...group.values()].sort((a, b) => a.time - b.time));
}

function outcome(scenario, eventsAfterStart) {
  if (scenario === "onboarding" || scenario === "knowledge") {
    const answer = eventsAfterStart.find(row => row.event === "assistant_answered" && row.status !== "error");
    if (scenario === "onboarding" || !answer) return answer?.time;
    return eventsAfterStart.find(row => row.event === "source_opened" && row.time >= answer.time)?.time;
  }
  const actions = new Map();
  for (const row of eventsAfterStart.filter(row => row.action !== null)) {
    if (!actions.has(row.action)) actions.set(row.action, {});
    const action = actions.get(row.action);
    if (row.event === "action_confirmed") action.confirmedAt ??= row.time;
    else {
      action.terminal = row.event;
      action.time = row.time;
    }
  }
  const confirmed = [...actions.values()].filter(action => action.confirmedAt !== undefined);
  if (!confirmed.length || confirmed.some(action =>
    action.terminal !== "action_succeeded" || action.time < action.confirmedAt)) return;
  return confirmed.reduce((latest, action) => Math.max(latest, action.time), -Infinity);
}

function median(numbers) {
  if (!numbers.length) return null;
  numbers.sort((a, b) => a - b);
  const middle = Math.floor(numbers.length / 2);
  return numbers.length % 2 ? numbers[middle] : (numbers[middle - 1] + numbers[middle]) / 2;
}

export function summarize(rows, cohort, mode) {
  if (!["test", "pilot"].includes(cohort) || !["rules", "model"].includes(mode)) {
    throw new Error("Укажите выборку (test или pilot) и режим (rules или model).");
  }
  const counts = Object.fromEntries(scenarios.map(name => [name, {
    started: 0, answered: 0, sourceOpened: 0, confirmed: 0, completed: 0,
    failedAction: 0, answerError: 0, degraded: 0, help: 0, repeatHelp: 0,
    durations: [], submissionDurations: [],
  }]));
  let withoutStart = 0;
  for (const group of groupEvents(rows)) {
    const start = group.find(row => row.event === "scenario_started" && row.scenario !== null);
    if (!start) {
      withoutStart++;
      continue;
    }
    if (group.some(row => row.event === "scenario_started" && row.scenario !== start.scenario)) {
      throw new Error("Один идентификатор прохождения использован для разных сценариев.");
    }
    const run = group.filter(row => row.time >= start.time && (row.scenario === start.scenario || row.scenario === null));
    const count = counts[start.scenario];
    const has = (event, status) => run.some(row => row.event === event && (!status || row.status === status));
    const help = run.filter(row => row.event === "human_help_requested").length;
    count.started++;
    count.answered += Number(has("assistant_answered", "ok") || has("assistant_answered", "degraded"));
    count.sourceOpened += Number(has("source_opened"));
    const firstSubmission = run.find(row => row.event === "action_confirmed");
    if (firstSubmission) {
      count.confirmed++;
      count.submissionDurations.push((firstSubmission.time - start.time) / 1000);
    }
    count.failedAction += Number(has("action_failed"));
    count.answerError += Number(has("assistant_answered", "error"));
    count.degraded += Number(has("assistant_answered", "degraded"));
    count.help += Number(help > 0);
    count.repeatHelp += Number(help > 1);
    const end = outcome(start.scenario, run);
    if (end !== undefined) {
      count.completed++;
      count.durations.push((end - start.time) / 1000);
    }
  }
  return {
    cohort, mode, withoutStart,
    scenarios: Object.fromEntries(Object.entries(counts).map(([name, { durations, submissionDurations, ...count }]) => [
      name, {
        ...count,
        completionRate: count.started ? count.completed / count.started : null,
        repeatHelpRate: count.started ? count.repeatHelp / count.started : null,
        medianSeconds: median(durations),
        medianSubmissionSeconds: median(submissionDurations),
      },
    ])),
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const [cohort, mode] = process.argv.slice(2);
    const input = readFileSync(0, "utf8").replace(/^\uFEFF/, "");
    console.log(JSON.stringify(summarize(JSON.parse(input), cohort, mode), null, 2));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
