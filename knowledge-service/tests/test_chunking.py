from dataclasses import FrozenInstanceError, replace

import pytest

from app.chunking import chunk_document
from app.loader import DocumentError, parse_document


@pytest.fixture
def document(raw_document):
    return parse_document(raw_document, filename="kb_absence_rules.md")


def test_sections_have_contract_ids_and_precise_text_ranges(document):
    chunks = chunk_document(document)
    assert [c.chunk_id for c in chunks] == ["kb_absence_rules#day-off", "kb_absence_rules#vacation", "kb_absence_rules#sick"]
    assert chunks[0].section == "Отгул"
    assert chunks[0].source == {"doc_id": document.doc_id, "chunk_id": "kb_absence_rules#day-off", "title": document.title, "section": "Отгул"}
    for chunk in chunks:
        assert chunk.text == "\n".join(document.text.splitlines()[chunk.start_line:chunk.end_line]).strip()
        assert chunk.document is document
        assert chunk.text


def test_ids_survive_text_and_heading_edits_and_reordering(document):
    edited = replace(document, text="## Другое название {#sick}\nНовый текст.\n\n## Отгул {#day-off}\nДругой текст.")
    assert [c.chunk_id for c in chunk_document(edited)] == ["kb_absence_rules#sick", "kb_absence_rules#day-off"]
    assert chunk_document(edited)[0].chunk_id == chunk_document(document)[2].chunk_id


def test_nested_heading_and_fenced_code_remain_in_section(document):
    text = "## Раздел {#one}\nВступление\n### Детали\nТекст\n```md\n## Не раздел {#fake}\n```\n~~~\n## Тоже код\n~~~\n## Второй {#two}\nКонец"
    chunks = chunk_document(replace(document, text=text))
    assert [c.anchor for c in chunks] == ["one", "two"]
    assert "### Детали" in chunks[0].text and "{#fake}" in chunks[0].text


@pytest.mark.parametrize("text", [
    "# Только заголовок", "## Нет якоря\nТекст", "## Пустой {#empty}\n",
    "## Один {#same}\nТекст\n## Два {#same}\nТекст", "## Неверный {#русский}\nТекст",
    "Текст вне раздела\n## Первый {#one}\nТекст", "# Название\nНе теряем вступление\n## Раздел {#one}\nТекст",
    "```\nТекст без раздела\n```", "## Раздел {#one}\n```\nНезакрытый код",
    "##    {#one}\nТекст",
])
def test_invalid_structure_is_not_silently_lost(document, text):
    with pytest.raises(DocumentError):
        chunk_document(replace(document, text=text))


def test_source_and_document_serializers_cannot_mutate_corpus(document):
    chunk = chunk_document(document)[0]
    result = chunk.to_result(1.25)
    assert result["score"] == 1.25 and result["updated_at"] == document.updated_at
    result["source"]["doc_id"] = "kb_other"
    exported = document.to_dict()
    exported["visibility"].append("role:manager")
    assert chunk.source["doc_id"] == document.doc_id
    assert document.visibility == ("public",)
    with pytest.raises(FrozenInstanceError):
        document.title = "Changed"


@pytest.mark.parametrize("score", [-1, float("nan"), float("inf"), True, "1", None])
def test_invalid_ranking_score_is_rejected(document, score):
    with pytest.raises(ValueError):
        chunk_document(document)[0].to_result(score)
