from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.access import Principal
from app.chunking import chunk_document
from app.knowledge import KnowledgeBase, KnowledgeView
from app.loader import load_documents
from app.search import SearchIndex, tokenize
from conftest import DATA, SECRET


def test_russian_forms_case_yo_and_terms():
    assert tokenize("ОТГУЛЫ отгулом отгула") == ["отгул"] * 3
    assert tokenize("СТАЖЁРА") == tokenize("стажера")
    assert tokenize("Когда daily?") == tokenize("стендап")
    assert tokenize("впн") == tokenize("VPN")
    assert tokenize("1:1") == ["oneonone"]
    assert tokenize("как что где !!!") == []


@pytest.mark.parametrize("query", ["Правила отгулов", "Инструкция для отгула", "Порядок оформления отгула"])
def test_generic_instruction_words_do_not_hide_the_topic(token, query):
    view = KnowledgeBase.load(DATA / "kb").authorize("Bearer " + token(), jwt_secret=SECRET)
    assert view.search(query)[0]["source"]["chunk_id"] == "kb_absence_rules#day-off"
    assert view.search("Правила ипотеки") == []


def test_actual_data_ranked_stably_with_bounded_results(token):
    view = KnowledgeBase.load(DATA / "kb").authorize("Bearer " + token(), jwt_secret=SECRET)
    results = view.search("как оформить отгул", 2)
    assert results[0]["source"]["chunk_id"] == "kb_absence_rules#day-off"
    assert len(results) == 2
    assert [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True)
    assert view.search("как оформить отгул", 2) == results
    assert view.search("парковка") == []
    assert view.search("доступ к медицинской страховке") == []
    assert view.search("как что где") == []


def test_search_works_with_new_files_and_preserves_body(tmp_path):
    raw = '''---
id: kb_custom
title: "Калибровка датчика"
visibility: ["public"]
tags: ["датчик"]
updated_at: "2026-11-12"
disclaimer: "Тестовая инструкция, не является регламентом Авито"
---
## Калибровка {#calibration}
Для калибровки датчика измерьте напряжение мультиметром.
'''
    (tmp_path / "kb_custom.md").write_text(raw)
    docs = load_documents(tmp_path)
    index = SearchIndex(chunk_document(docs[0]))
    result = index.search("калибровку датчиков")[0]
    assert result["source"]["chunk_id"] == "kb_custom#calibration"
    assert result["text"] == "Для калибровки датчика измерьте напряжение мультиметром."


def test_private_documents_never_affect_ranking_or_scores(token):
    docs = load_documents(DATA / "kb")
    original = KnowledgeBase(docs, tuple(c for d in docs for c in chunk_document(d)))
    private = replace(docs[0], doc_id="kb_secret", visibility=("team:team_auto",),
                      title="Отгул", text="## Отгул {#secret}\n" + "Отгул отпуск " * 500)
    changed = KnowledgeBase(docs + (private,), tuple(c for d in docs + (private,) for c in chunk_document(d)))
    header = "Bearer " + token()
    assert original.authorize(header, jwt_secret=SECRET).search("отгул") == changed.authorize(header, jwt_secret=SECRET).search("отгул")


def test_cached_indexes_follow_allowed_sets_and_results_are_detached(token):
    base = KnowledgeBase.load(DATA / "kb")
    anna = base.authorize("Bearer " + token(), jwt_secret=SECRET)
    maximum = base.authorize("Bearer " + token(sub="u_max", team_id="team_auto"), jwt_secret=SECRET)
    mentor = base.authorize("Bearer " + token(sub="u_igor", role="mentor"), jwt_secret=SECRET)
    assert anna.search("стендап")
    assert maximum.search("стендап") == []
    assert mentor.search("напутственное слово")
    assert anna.search("напутственное слово") == []
    result = anna.search("стендап")
    result[0]["source"]["title"] = "mutated"
    assert anna.search("стендап")[0]["source"]["title"] != "mutated"
    assert base._search_index.cache_info().currsize == 3


def test_empty_corpus_and_direct_view():
    assert SearchIndex(()).search("отгул") == []
    assert KnowledgeView((), (), Principal("u_x", "x", "intern", None)).search("отгул") == []


def test_ties_are_ordered_by_id():
    doc = load_documents(DATA / "kb")[0]
    first = replace(doc, doc_id="kb_z", text="## Один {#one}\nУникальный калибратор.")
    second = replace(first, doc_id="kb_a")
    index = SearchIndex(chunk_document(first) + chunk_document(second))
    assert [r["source"]["doc_id"] for r in index.search("калибратор")] == ["kb_a", "kb_z"]


def test_parallel_stemming_and_search_are_deterministic(token):
    base = KnowledgeBase.load(DATA / "kb")
    queries = ["отгула", "стендапы", "незавершённые задачи", "первая неделя", "выдача доступа"]
    view = base.authorize("Bearer " + token(), jwt_secret=SECRET)
    expected = [view.search(query) for query in queries]
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(view.search, queries * 10))
    assert actual == expected * 10


@pytest.mark.parametrize("query,top_k", [("", 1), (" " , 1), ("x" * 1001, 1), (None, 1), ("x", 0), ("x", 11), ("x", True)])
def test_direct_search_rejects_invalid_parameters(query, top_k):
    with pytest.raises(ValueError):
        SearchIndex(()).search(query, top_k)


def test_pronouns_do_not_block_a_one_word_question():
    # «Во сколько у нас стендап?» — главный демо-вопрос: «нас» не должно съедать долю совпадения.
    from app.search import tokenize
    assert tokenize("Во сколько у нас стендап?") == tokenize("стендап")
    assert tokenize("Что нам делать с доступами?") == tokenize("доступами")


@pytest.mark.parametrize("query, expected", [
    ("Как настроить окружение?", {"kb_onboarding_first_weeks#week1", "kb_delivery_dev_setup#first-run"}),  # настро / настр
    ("Как поднять проект локально?", {"kb_delivery_dev_setup#first-run"}),  # подня / подн
])
def test_verb_forms_one_letter_apart_match(token, query, expected):
    view = KnowledgeBase.load(DATA / "kb").authorize("Bearer " + token(), jwt_secret=SECRET)
    found = [r["source"]["chunk_id"] for r in view.search(query, 3)]
    assert found and found[0] in expected


def test_near_forms_are_one_letter_apart_and_weigh_less():
    chunks = tuple(c for d in load_documents(DATA / "kb") for c in chunk_document(d))
    index = SearchIndex(chunks)
    assert index.forms("настро").get("настр") == 0.9  # «настроить» находит «Настрой», но весит меньше точного
    assert "стенд" not in index.forms("стендап")  # «стенды» на тестовых стендах — не «стендап»
    assert index.forms("кот") == ({"кот": 1.0} if "кот" in index.idf else {})  # короткие основы не расширяем
    assert SearchIndex(chunks, enhanced=False).forms("настро") == ({"настро": 1.0} if "настро" in index.idf else {})
