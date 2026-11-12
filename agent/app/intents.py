"""Распознавание запросов без LLM: «что делать дальше», отгул или отпуск с датами (A3), доступы (A7)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

NEXT_STEPS = re.compile(r"что (?:мне )?(?:делать|сделать)|что дальше|с чего начать|следующ\w* шаг|план на (?:неделю|сегодня)")
ABSENCE = re.compile(r"отгул|отпуск|выходн\w* день|отпроситься")

MONTH = r"(январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}
# Полные формы, чтобы «среди недели» не стало средой.
WEEKDAYS = ("понедельник", "вторник", "сред[ау]", "четверг", "пятниц[аеуы]", "суббот[аеуы]", "воскресень[ея]")
RELATIVE = {"сегодня": 0, "послезавтра": 2, "завтра": 1}

# Системы из контракта C (AccessSystem) и как их называют в переписке.
SYSTEMS = {
    "confluence": r"confluence|конфлюенс\w*|вики",
    "jira": r"jira|джир\w*",
    "gitlab": r"gitlab|гитлаб\w*|гит[ае]?|репозитор\w*",
    "vpn": r"vpn|впн",
    "team_space": r"пространств\w*",
}
ACCESS = re.compile(r"доступ")
WANTS = re.compile(r"запрос|оформ|получ|выда|дай|нуж[еенао]|хочу|подай|заявк|открой|сделай")


@dataclass(frozen=True)
class Understanding:
    intent: str  # next_steps | absence | access | unknown (вопрос по базе знаний)
    kind: str | None = None  # day_off | vacation
    date_from: date | None = None
    date_to: date | None = None
    past: bool = False  # названная дата уже прошла
    systems: tuple[str, ...] = ()  # названные системы доступа, в порядке упоминания
    wants: bool = False  # просит оформить доступ, а не только узнать


def understand(message: str, today: date, state: dict[str, Any] | None) -> Understanding:
    text = message.lower()
    dates = find_dates(text, today)
    continuing = (state or {}).get("intent") == "absence_request" and bool(dates)
    if ABSENCE.search(text) or continuing:
        kind = "vacation" if "отпуск" in text else (state or {}).get("kind", "day_off")
        if not dates:
            return Understanding("absence", kind)
        start, end = min(dates[0], dates[-1]), max(dates[0], dates[-1])
        if start < today:
            return Understanding("absence", kind, past=True)
        return Understanding("absence", kind, start, end)
    systems = find_systems(text)
    if (state or {}).get("intent") == "access_request" and systems:
        return Understanding("access", systems=systems, wants=True)
    wants = bool(WANTS.search(text))
    # «Как работает VPN?» — вопрос по базе знаний; «нужен VPN» и «доступы» — про доступ.
    if ACCESS.search(text) or (systems and wants):
        return Understanding("access", systems=systems, wants=wants)
    if NEXT_STEPS.search(text):
        return Understanding("next_steps")
    return Understanding("unknown")


def find_systems(text: str) -> tuple[str, ...]:
    found = sorted((m.start(), system) for system, p in SYSTEMS.items() for m in re.finditer(rf"\b(?:{p})\b", text))
    return tuple(dict.fromkeys(system for _, system in found))


def find_dates(text: str, today: date) -> list[date]:
    """Даты из текста в порядке упоминания. Неразборчивые и несуществующие даты пропускаются."""
    found: list[tuple[int, date]] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match[str]) -> bool:
        return all(m.end() <= a or m.start() >= b for a, b in taken)

    def add(pos: int, value: date | None) -> None:
        if value is not None:
            found.append((pos, value))

    patterns = [
        (rf"\b(\d{{1,2}})\s*(?:-|–|—|по)\s*(\d{{1,2}})\s+{MONTH}", lambda m: [
            _day_month(int(m[1]), _month(m[3]), None, today), _day_month(int(m[2]), _month(m[3]), None, today)]),
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: [_safe(int(m[1]), int(m[2]), int(m[3]))]),
        (r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?\b", lambda m: [
            _day_month(int(m[1]), int(m[2]), _year(m[3]), today)]),
        (rf"\b(\d{{1,2}})\s+{MONTH}(?:\s+(\d{{4}}))?", lambda m: [
            _day_month(int(m[1]), _month(m[2]), _year(m[3]), today)]),
        (r"\b(послезавтра|завтра|сегодня)\b", lambda m: [today + timedelta(days=RELATIVE[m[1]])]),
    ] + [
        (rf"\b{word}\b", lambda m, day=day: [_next_weekday(today, day)]) for day, word in enumerate(WEEKDAYS)
    ]
    for pattern, convert in patterns:
        for m in re.finditer(pattern, text):
            if free(m):
                taken.append((m.start(), m.end()))
                for value in convert(m):
                    add(m.start(), value)
    return [value for _, value in sorted(found, key=lambda item: item[0])]


def _month(word: str) -> int:
    return MONTHS[word[:3]]


def _year(raw: str | None) -> int | None:
    if raw is None:
        return None
    return int(raw) + 2000 if len(raw) == 2 else int(raw)


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _day_month(day: int, month: int, year: int | None, today: date) -> date | None:
    if year is not None:
        return _safe(year, month, day)
    value = _safe(today.year, month, day)
    # Дата без года, которая в этом году уже прошла, — это следующий год.
    if value is not None and value < today:
        value = _safe(today.year + 1, month, day)
    return value


def _next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)
