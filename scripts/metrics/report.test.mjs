import assert from "node:assert/strict";
import { test } from "node:test";
import { summarize } from "./report.mjs";

function event(run, id, seconds, scenario, name, status = null, action = null) {
  return {
    run, event_id: id, scenario, event: name, status, action,
    source: name.startsWith("action_") || name === "assistant_answered" ? "server" : "client",
    recorded_at: new Date(Date.UTC(2026, 10, 13) + seconds * 1000).toISOString(),
  };
}

test("дедупликация, согласование, отказ и медиана по завершённым прохождениям", () => {
  const sent = event(1, "send", 15, "absence", "action_confirmed", "submitted", 1);
  const help = event(1, "help", 2, "absence", "human_help_requested");
  const rows = [
    event(1, "done", 40, "absence", "action_succeeded", "approved", 1),
    sent, sent, help, help, event(1, "help2", 3, "absence", "human_help_requested"),
    event(1, "start", 0, "absence", "scenario_started"),
    event(1, "retry-start", 5, "absence", "scenario_started"),
    event(1, "degraded", 4, null, "assistant_answered", "degraded"),
    event(2, "start", 0, "absence", "scenario_started"),
    event(2, "send", 5, "absence", "action_confirmed", "submitted", 1),
    event(2, "done", 20, "absence", "action_succeeded", "approved", 1),
    event(3, "start", 0, "absence", "scenario_started"),
    event(3, "send", 5, "absence", "action_confirmed", "submitted", 1),
    event(3, "no", 10, "absence", "action_failed", "rejected", 1),
    event(4, "orphan", 1, null, "assistant_answered", "error"),
  ];
  const report = summarize(rows, "test", "model");
  assert.equal(report.cohort, "test");
  assert.equal(report.mode, "model");
  assert.equal(report.withoutStart, 1);
  assert.deepEqual(report.scenarios.absence, {
    started: 3, answered: 1, sourceOpened: 0, confirmed: 3, completed: 2,
    failedAction: 1, answerError: 0, degraded: 1, help: 1, repeatHelp: 1,
    completionRate: 2 / 3, repeatHelpRate: 1 / 3, medianSeconds: 30, medianSubmissionSeconds: 5,
  });
});

test("доступ выдан по всем подтверждённым карточкам, источник открыт после ответа", () => {
  const rows = [
    event(1, "start", 0, "access", "scenario_started"),
    event(1, "send1", 5, "access", "action_confirmed", "submitted", 1),
    event(1, "send2", 6, "access", "action_confirmed", "submitted", 2),
    event(1, "grant1", 7, "access", "action_succeeded", "approved", 1),
    event(2, "start", 0, "knowledge", "scenario_started"),
    event(2, "early", 1, "knowledge", "source_opened"),
    event(2, "error", 2, "knowledge", "assistant_answered", "error"),
    event(2, "answer", 3, "knowledge", "assistant_answered", "ok"),
    event(3, "start", 0, "onboarding", "scenario_started"),
    event(3, "answer", 4, "onboarding", "assistant_answered", "ok"),
  ];
  const first = summarize(rows, "pilot", "rules").scenarios;
  assert.equal(first.access.completed, 0);
  assert.equal(first.knowledge.completed, 0);
  assert.equal(first.knowledge.answerError, 1);
  assert.equal(first.onboarding.medianSeconds, 4);
  rows.push(event(1, "grant2", 12, "access", "action_succeeded", "approved", 2));
  rows.push(event(2, "opened", 8, "knowledge", "source_opened"));
  const second = summarize(rows, "pilot", "rules").scenarios;
  assert.equal(second.access.medianSeconds, 12);
  assert.equal(second.knowledge.medianSeconds, 8);
  assert.equal(second.absence.completionRate, null);
});

test("пустая выгрузка, конфликт повтора и обязательные метки", () => {
  assert.equal(summarize([], "test", "rules").scenarios.knowledge.medianSeconds, null);
  assert.throws(() => summarize([], "test", undefined), /режим/);
  const start = event(1, "start", 0, "knowledge", "scenario_started");
  assert.throws(() => summarize([start, { ...start, scenario: "access" }], "test", "rules"), /идентификатор события/);
  assert.throws(() => summarize([start, { ...start, event_id: "new", scenario: "access" }], "test", "rules"), /разных сценариев/);
});

test("событие успеха до подтверждения не завершает заявку", () => {
  const rows = [
    event(1, "start", 0, "access", "scenario_started"),
    event(1, "grant", 1, "access", "action_succeeded", "approved", 1),
    event(1, "send", 2, "access", "action_confirmed", "submitted", 1),
  ];
  assert.equal(summarize(rows, "test", "rules").scenarios.access.completed, 0);
});
