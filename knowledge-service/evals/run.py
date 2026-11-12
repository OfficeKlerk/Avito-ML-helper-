"""Run: python -m evals.run --check. Labels never enter the search application."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import jwt
import yaml

from app.knowledge import KnowledgeBase
from app.search import SearchIndex

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
CASES = Path(__file__).with_name("cases.yaml")


def evaluate(*, data: Path = DATA, cases_path: Path = CASES, split: str = "all") -> dict:
    cases = yaml.safe_load(cases_path.read_text())
    users = {u["id"]: u for u in json.loads((data / "seed" / "users.json").read_text())}
    knowledge = KnowledgeBase.load(data / "kb")
    secret = secrets.token_hex(32)
    rows, seen = [], set()
    for case in cases:
        if case["id"] in seen or case["split"] not in {"dev", "holdout"}:
            raise ValueError("duplicate case id or unknown split")
        seen.add(case["id"])
        if split != "all" and case["split"] != split:
            continue
        user = users[case["user"]]
        token = jwt.encode({"sub": user["id"], "login": user["login"], "role": user["role"],
                            "team_id": user["team_id"], "exp": int(time.time()) + 3600}, secret, algorithm="HS256")
        view = knowledge.authorize("Bearer " + token, jwt_secret=secret)
        allowed = {c.chunk_id for c in view.chunks()}
        expected = set(case["relevant"])
        if not expected.issubset(allowed):
            raise ValueError(f"invalid expected source or ACL: {case['id']}")
        for name, enhanced in [("baseline", False), ("improved", True)]:
            # Default uses exactly the production authorization/cache/search path.
            results = view.search(case["query"], 5) if enhanced else SearchIndex(view.chunks(), enhanced=False).search(case["query"], 5)
            actual = [r["source"]["chunk_id"] for r in results]
            rank = next((i for i, chunk_id in enumerate(actual, 1) if chunk_id in expected), None)
            leaks = [r["source"]["chunk_id"] for r in results if r["source"]["chunk_id"] not in allowed
                     or r["source"]["doc_id"] in case.get("forbidden", [])]
            rows.append({**case, "mode": name, "actual": actual, "first_relevant_rank": rank,
                         "correct_empty": not actual if not expected else None, "leaks": leaks})
    if not rows:
        raise ValueError("evaluation has no cases")
    metrics = {}
    for mode in ["baseline", "improved"]:
        metrics[mode] = {}
        for group in ["dev", "holdout", "all"]:
            subset = [r for r in rows if r["mode"] == mode and (group == "all" or r["split"] == group)]
            if not subset:
                continue
            positive = [r for r in subset if r["relevant"]]
            negative = [r for r in subset if not r["relevant"]]
            metrics[mode][group] = {
                "cases": len(subset), "answerable": len(positive), "unanswerable": len(negative),
                **{f"recall_at_{k}": sum(r["first_relevant_rank"] is not None and r["first_relevant_rank"] <= k for r in positive) / len(positive) if positive else None for k in [1, 3, 5]},
                "mrr": sum(1 / r["first_relevant_rank"] if r["first_relevant_rank"] else 0 for r in positive) / len(positive) if positive else None,
                "empty_accuracy": sum(r["correct_empty"] for r in negative) / len(negative) if negative else None,
                "leaks": sum(len(r["leaks"]) for r in subset),
            }
    corpus = hashlib.sha256()
    for path in sorted((data / "kb").rglob("*.md")):
        corpus.update(path.relative_to(data).as_posix().encode() + b"\0" + path.read_bytes())
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "corpus_sha256": corpus.hexdigest(),
            "evaluation_phase": "regression_after_holdout_review",
            "search_code_sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / "app/search.py").read_bytes()).hexdigest(),
            "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(), "metrics": metrics, "cases": rows}


def meets_targets(report: dict) -> bool:
    groups = report["metrics"]["improved"]
    return all(m["recall_at_3"] is not None and m["recall_at_3"] >= .85
               and m["empty_accuracy"] is not None and m["empty_accuracy"] >= .9
               and m["leaks"] == 0 for name, m in groups.items() if name != "all")


def markdown(report: dict) -> str:
    lines = ["# Качество поиска knowledge-service", "", f"Запуск: {report['generated_at']}",
             f"Корпус SHA-256: `{report['corpus_sha256']}`", f"Вопросы SHA-256: `{report['cases_sha256']}`", "",
             "Recall@k здесь — доля вопросов, для которых хотя бы один размеченный правильный фрагмент попал в первые k результатов.",
             "MRR считается по первому правильному фрагменту. Пустые ответы оцениваются отдельно. Утечки считаются по всем пяти результатам.", "",
             "| Вариант | Выборка | Вопросов | Recall@1 | Recall@3 | Recall@5 | MRR | Пустые ответы | Утечки |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for mode, groups in report["metrics"].items():
        for split, values in groups.items():
            rates = [values[k] for k in ["recall_at_1", "recall_at_3", "recall_at_5", "mrr", "empty_accuracy"]]
            formatted = [f"{v:.1%}" if v is not None else "—" for v in rates]
            lines.append(f"| {mode} | {split} | {values['cases']} | " + " | ".join(formatted) + f" | {values['leaks']} |")
    lines += ["", "Baseline: BM25 по точным словам. Improved: русские основы слов, служебные слова, словарь терминов, веса заголовков и порог покрытия запроса.",
              "Параметры: k1=1.5, b=0.75, покрытие запроса >=60%; тело ×1, заголовок раздела ×3, название документа ×2, теги ×1. Итоговый score умножается на покрытие запроса и на (1 + доля слов запроса в заголовке раздела).",
              "Порог приёмки: Recall@3 ≥85%, корректные пустые ответы ≥90%, утечек 0 отдельно на dev и holdout.",
              "Набор синтетический, малый; метрики не доказывают качество на произвольных реальных запросах.",
              "Первый нетронутый holdout сохранён в first-holdout.md/json: Recall@3 92.9%, пустые ответы 100%, утечек 0. После разбора одного промаха добавлены общие слова «правила/инструкция/порядок/оформление» и нормализация словоформ стоп-слов. Столбец holdout в latest — теперь регрессионная проверка тех же вопросов, не новая независимая оценка.", "",
              "## Ошибки improved", ""]
    failures = [r for r in report["cases"] if r["mode"] == "improved" and
                (r["leaks"] or (r["relevant"] and (r["first_relevant_rank"] is None or r["first_relevant_rank"] > 3))
                 or (not r["relevant"] and not r["correct_empty"]))]
    lines += [f"- {r['id']} ({r['split']}): {r['query']} → {', '.join(r['actual']) or 'пусто'}" for r in failures] or ["Нет ошибок по порогам приёмки для отдельных вопросов."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("reports"))
    parser.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = evaluate(split=args.split)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "latest.md").write_text(markdown(report))
    print(markdown(report))
    return 1 if args.check and not meets_targets(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
