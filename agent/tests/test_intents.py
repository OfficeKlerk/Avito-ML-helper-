"""A3: распознавание запросов и дат. Сегодня во всех тестах — среда, 11 ноября 2026."""

from datetime import date

import pytest

from app.intents import find_dates, understand

TODAY = date(2026, 11, 11)
D = date


@pytest.mark.parametrize(
    "text, expected",
    [
        ("сегодня", [D(2026, 11, 11)]),
        ("завтра", [D(2026, 11, 12)]),
        ("послезавтра", [D(2026, 11, 13)]),
        ("в пятницу", [D(2026, 11, 13)]),
        ("в среду", [D(2026, 11, 11)]),  # тот же день недели — сегодня
        ("в понедельник", [D(2026, 11, 16)]),
        ("13 ноября", [D(2026, 11, 13)]),
        ("13 ноября 2027", [D(2027, 11, 13)]),
        ("5 января", [D(2027, 1, 5)]),  # без года и уже прошла — следующий год
        ("1 мая", [D(2027, 5, 1)]),
        ("13.11", [D(2026, 11, 13)]),
        ("13.11.2026", [D(2026, 11, 13)]),
        ("13.11.26", [D(2026, 11, 13)]),
        ("2026-11-20", [D(2026, 11, 20)]),
        ("с 13 по 15 ноября", [D(2026, 11, 13), D(2026, 11, 15)]),
        ("13–15 ноября", [D(2026, 11, 13), D(2026, 11, 15)]),
        ("с 13.11 по 15.11", [D(2026, 11, 13), D(2026, 11, 15)]),
        ("с 15 декабря по 2027-01-10", [D(2026, 12, 15), D(2027, 1, 10)]),
        ("31.02", []),  # такой даты нет
        ("2026-13-01", []),
        ("отгул среди недели", []),  # «среди» — не среда
        ("просто вопрос", []),
    ],
)
def test_find_dates(text, expected):
    assert find_dates(text, TODAY) == expected


def test_next_steps_phrases():
    for text in ("Что мне делать дальше?", "что дальше", "С чего начать?", "какой следующий шаг", "план на неделю"):
        assert understand(text, TODAY, None).intent == "next_steps", text


def test_absence_without_date_asks():
    nlu = understand("Как оформить отгул?", TODAY, None)
    assert (nlu.intent, nlu.kind, nlu.date_from, nlu.past) == ("absence", "day_off", None, False)


def test_absence_with_date():
    nlu = understand("Хочу взять отгул в пятницу", TODAY, None)
    assert (nlu.kind, nlu.date_from, nlu.date_to) == ("day_off", D(2026, 11, 13), D(2026, 11, 13))


def test_vacation_range_in_any_order():
    nlu = understand("Отпуск с 20 по 15 декабря", TODAY, None)
    assert (nlu.kind, nlu.date_from, nlu.date_to) == ("vacation", D(2026, 12, 15), D(2026, 12, 20))


def test_absence_wins_over_next_steps():
    assert understand("Что мне делать, если нужен отгул завтра?", TODAY, None).intent == "absence"


def test_past_date():
    nlu = understand("отгул на 01.11.2026", TODAY, None)
    assert (nlu.intent, nlu.past, nlu.date_from) == ("absence", True, None)


def test_continuation_keeps_kind():
    state = {"intent": "absence_request", "kind": "vacation"}
    nlu = understand("с 1 по 5 декабря", TODAY, state)
    assert (nlu.intent, nlu.kind, nlu.date_from, nlu.date_to) == ("absence", "vacation", D(2026, 12, 1), D(2026, 12, 5))


def test_topic_change_drops_absence():
    state = {"intent": "absence_request", "kind": "day_off"}
    assert understand("Что мне делать дальше?", TODAY, state).intent == "next_steps"
    assert understand("кто мой наставник", TODAY, state).intent == "unknown"


def test_dates_without_absence_context_are_not_absence():
    assert understand("что было 13 ноября", TODAY, None).intent == "unknown"
