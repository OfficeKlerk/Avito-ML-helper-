"""Run the frozen Q4 cases and retain evidence for review."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from time import monotonic

import yaml

from app import contract
from app.chat import answer, claims_draft
from app.llm import model_from_env

from .environment import EvalTools, LocalCorp, LocalKnowledge, chat_request

CASES = Path(__file__).with_name("q4_cases.yaml")
UNAVAILABLE = re.compile(
    r"не наш[её]л|не удалось найти|нет (?:точн\w* |доступн\w* |подтвержд[её]н\w* )?"
    r"(?:информаци|данн|сведени|ответ|доступ)|недоступ|не вижу|не могу|нет в|не указан|"
    r"не подтвержд|не располага|не знаю|не найден",
    re.IGNORECASE,
)


def assess(case, reply, tools):
    problems = list(contract.errors(reply, "ChatResponse"))
    text = " ".join(reply["text"].split())
    sources = {item["chunk_id"] for item in reply["sources"]}
    visible = {
        chunk["chunk_id"] for chunk in tools.knowledge.chunks
        if tools.knowledge.allowed(chunk, tools.corp.users[tools.user_id])
    }
    for source in sorted(sources - visible):
        problems.append(f"недоступный или неизвестный источник: {source}")
    for fact in case.get("facts", []):
        if not re.search(fact["pattern"], text, re.IGNORECASE):
            problems.append(f"нет ожидаемого факта: {fact['pattern']}")
        if fact.get("source") and fact["source"] not in sources:
            problems.append(f"нет подтверждающего раздела: {fact['source']}")
    if case.get("unavailable") and not UNAVAILABLE.search(text):
        problems.append("ответ не сообщил, что сведения недоступны")
    if set(case.get("forbidden_sources", [])) & {item["doc_id"] for item in reply["sources"]}:
        problems.append("раскрыт закрытый документ")
    if case.get("forbidden_text") and re.search(case["forbidden_text"], text, re.IGNORECASE):
        problems.append("найден запрещённый факт или утверждение о выполнении")
    drafts = reply["proposed_actions"]
    expected = case.get("drafts", [])
    if len(drafts) != len(expected):
        problems.append(f"черновиков {len(drafts)}, ожидалось {len(expected)}")
    for draft, want in zip(drafts, expected, strict=False):
        if draft["type"] != want["type"] or any(draft["fields"].get(k) != v for k, v in want["fields"].items()):
            problems.append("неверный тип или поля черновика")
    if not drafts and claims_draft(text):
        problems.append("заявлено действие без карточки")
    if reply["status"] != "ok":
        problems.append(f"статус ответа: {reply['status']}")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["rules", "model"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Файл уже существует. Для следующего прогона укажи новый путь.")
    model = model_from_env() if args.mode == "model" else None
    if args.mode == "model" and model is None:
        parser.error("Для прогона с моделью нужна конфигурация LLM.")
    raw = CASES.read_bytes()
    cases = yaml.safe_load(raw)["cases"]
    knowledge = LocalKnowledge()
    rows = []
    for case in cases:
        corp = LocalCorp()
        request_id = f"rq-q4-{case['id']}"
        tools = EvalTools(case["user"], request_id, knowledge, corp)
        body = chat_request(corp, case["user"], case["message"], request_id)
        started = monotonic()
        reply = answer(body, tools, model)
        problems = assess(case, reply, tools)
        rows.append({
            "id": case["id"], "passed": not problems, "problems": problems,
            "elapsed_ms": round((monotonic() - started) * 1000), "reply": reply,
        })
        print(f"{case['id']}: {'PASS' if not problems else 'FAIL'}", flush=True)
    report = {
        "cases_sha256": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
        "mode": args.mode, "model": model.model if model else None,
        "passed": sum(row["passed"] for row in rows), "total": len(rows), "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"{report['passed']}/{report['total']} — {args.output}")


if __name__ == "__main__":
    main()
