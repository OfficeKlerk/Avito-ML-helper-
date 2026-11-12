from pathlib import Path

import pytest

from app.loader import CorpusLoadError, DocumentError, load_documents, parse_document
from conftest import DATA


def parse(raw):
    return parse_document(raw, filename="kb_absence_rules.md")


def test_load_existing_documents_preserves_metadata_and_body():
    documents = load_documents(DATA / "kb")
    assert len(documents) >= 9
    assert [d.doc_id for d in documents] == sorted(d.doc_id for d in documents)
    absence = next(d for d in documents if d.doc_id == "kb_absence_rules")
    assert absence.doc_id == "kb_absence_rules"
    assert absence.visibility == ("public",)
    assert absence.updated_at == "2026-11-02"
    assert absence.text.startswith("# Как оформить")
    assert "visibility:" not in absence.text
    assert "{#day-off}" in absence.text


def test_bom_crlf_and_unquoted_dates(raw_document):
    document = parse("\ufeff" + raw_document.replace('"2026-11-02"', '2026-11-02').replace("\n", "\r\n"))
    assert document.updated_at == "2026-11-02"
    assert "\r" not in document.text


@pytest.mark.parametrize("old,new", [
    ('id: kb_absence_rules', 'id: kb_other'),
    ('id: kb_absence_rules', 'id: kb_bad#id'),
    ('title: "Как оформить отгул или отпуск"', 'title: " "'),
    ('title: "Как оформить отгул или отпуск"', 'title: 123'),
    ('visibility: ["public"]', 'visibility: []'),
    ('visibility: ["public"]', 'visibility: public'),
    ('visibility: ["public"]', 'visibility: ["role:admin"]'),
    ('visibility: ["public"]', 'visibility: ["team:any"]'),
    ('visibility: ["public"]', 'visibility: ["public", "public"]'),
    ('visibility: ["public"]', 'visibility: ["public", null]'),
    ('tags: ["отгул", "отпуск", "отсутствие"]', 'tags: {}'),
    ('tags: ["отгул", "отпуск", "отсутствие"]', 'tags: ["отгул", "отгул"]'),
    ('updated_at: "2026-11-02"', 'updated_at: "2026-02-30"'),
    ('updated_at: "2026-11-02"', 'updated_at: 2026-02-30'),
    ('updated_at: "2026-11-02"', 'updated_at: "20261102"'),
    ('updated_at: "2026-11-02"', 'updated_at: 2026-11-02T10:00:00Z'),
    ('updated_at: "2026-11-02"', 'updated_at: true'),
    ('disclaimer: "Тестовая инструкция, не является регламентом Авито"', 'disclaimer: "Настоящий регламент"'),
    ('visibility: ["public"]', 'visibility: ["team:team_delivery"]\nvisibility: ["public"]'),
    ('visibility: ["public"]', 'visibility: ["public"]\nvisiblity: ["public"]'),
    ('visibility: ["public"]\n', ''),
])
def test_invalid_metadata_is_rejected(raw_document, old, new):
    with pytest.raises(DocumentError):
        parse(raw_document.replace(old, new))


@pytest.mark.parametrize("raw", [
    "", "# No YAML", "---\nid: kb_absence_rules", "---\n[]\n---\ntext",
    "---\n42: value\n---\ntext", "---\nid: [unclosed\n---\ntext",
    "---\nid: !!python/object/apply:os.system ['echo unsafe']\n---\ntext",
])
def test_bad_front_matter(raw):
    with pytest.raises(DocumentError):
        parse(raw)


def test_empty_document_body(raw_document):
    header = raw_document.split("---", 2)[1]
    with pytest.raises(DocumentError, match="пустое тело"):
        parse(f"---{header}---\n ")


def test_empty_and_missing_directory(tmp_path):
    for path in [tmp_path, tmp_path / "missing"]:
        with pytest.raises(CorpusLoadError):
            load_documents(path)


def test_errors_are_collected_without_partial_success(tmp_path, raw_document):
    (tmp_path / "kb_absence_rules.md").write_text(raw_document)
    (tmp_path / "bad.md").write_text("this text must not appear in diagnostics")
    (tmp_path / "invalid.md").write_bytes(b"\xff\xfe")
    with pytest.raises(CorpusLoadError) as error:
        load_documents(tmp_path)
    assert len(error.value.issues) == 2
    assert "bad.md" in str(error.value) and "invalid.md" in str(error.value)
    assert "this text must not appear" not in str(error.value)


def test_duplicate_id_in_subdirectories(tmp_path, raw_document):
    (tmp_path / "kb_absence_rules.md").write_text(raw_document)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "kb_absence_rules.md").write_text(raw_document)
    with pytest.raises(CorpusLoadError, match="повторяющийся id"):
        load_documents(tmp_path)


def test_symlink_is_rejected(tmp_path):
    (tmp_path / "kb_absence_rules.md").symlink_to(DATA / "kb" / "kb_absence_rules.md")
    with pytest.raises(CorpusLoadError, match="символические ссылки"):
        load_documents(tmp_path)


def test_unreadable_file(tmp_path, monkeypatch, raw_document):
    (tmp_path / "kb_absence_rules.md").write_text(raw_document)
    def denied(*args, **kwargs):
        raise PermissionError("sensitive details")
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(CorpusLoadError) as error:
        load_documents(tmp_path)
    assert "PermissionError" in str(error.value)
    assert "sensitive details" not in str(error.value)
