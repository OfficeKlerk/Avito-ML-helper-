"""K1: validate Markdown documents before making the corpus available."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from .models import Document

DOC_ID = re.compile(r"kb_[a-z0-9_]+")
VISIBILITY = re.compile(r"(?:public|team:team_[a-z0-9_]+|role:(?:intern|mentor|manager|hr))")
FIELDS = {"id", "title", "visibility", "tags", "updated_at", "disclaimer"}


class DocumentError(ValueError):
    """Safe diagnostic: field/structure only, never the document contents."""


class CorpusLoadError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = tuple(issues)
        super().__init__("База знаний не загружена:\n" + "\n".join(issues))


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in keys:
                raise DocumentError("YAML: ключи должны быть строками и не повторяться")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _nonempty_string(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentError(f"{field}: требуется непустая строка")
    return value.strip()


def _string_list(value, field: str, *, nonempty=False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise DocumentError(f"{field}: требуется {'непустой ' if nonempty else ''}список строк")
    result = tuple(_nonempty_string(item, field) for item in value)
    if len(set(result)) != len(result):
        raise DocumentError(f"{field}: повторяющиеся значения")
    return result


def parse_document(raw: str, *, filename: str) -> Document:
    lines = raw.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise DocumentError("нет YAML-шапки в начале файла")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise DocumentError("YAML-шапка не закрыта")
    try:
        meta = yaml.load("\n".join(lines[1:end]), Loader=_UniqueKeyLoader)
    except DocumentError:
        raise
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        # YAML parser messages can contain the offending text; do not expose them.
        raise DocumentError("неверный YAML в шапке") from exc
    if not isinstance(meta, dict):
        raise DocumentError("YAML-шапка должна быть объектом")
    if set(meta) != FIELDS:
        missing = sorted(FIELDS - set(meta))
        # Do not echo arbitrary unknown keys supplied in the document.
        raise DocumentError(f"поля шапки не соответствуют формату; отсутствуют: {', '.join(missing) or 'нет'}")
    doc_id = _nonempty_string(meta["id"], "id")
    if not DOC_ID.fullmatch(doc_id) or Path(filename).stem != doc_id:
        raise DocumentError("id: неверный формат или не совпадает с именем файла")
    visibility = _string_list(meta["visibility"], "visibility", nonempty=True)
    if any(not VISIBILITY.fullmatch(rule) for rule in visibility):
        raise DocumentError("visibility: правило не соответствует контракту E")
    raw_date = meta["updated_at"]
    if type(raw_date) is date:  # YAML also supports unquoted ISO dates.
        updated_at = raw_date.isoformat()
    elif isinstance(raw_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        try:
            updated_at = date.fromisoformat(raw_date).isoformat()
        except ValueError as exc:
            raise DocumentError("updated_at: неверная календарная дата") from exc
    else:
        raise DocumentError("updated_at: требуется дата YYYY-MM-DD")
    disclaimer = _nonempty_string(meta["disclaimer"], "disclaimer")
    if "не является регламентом" not in disclaimer.casefold():
        raise DocumentError("disclaimer: нет пометки тестовой инструкции")
    text = "\n".join(lines[end + 1:]).strip()
    if not text:
        raise DocumentError("пустое тело документа")
    return Document(
        doc_id=doc_id, title=_nonempty_string(meta["title"], "title"),
        visibility=visibility, tags=_string_list(meta["tags"], "tags"),
        updated_at=updated_at, disclaimer=disclaimer, text=text,
    )


def load_documents(directory: str | Path) -> tuple[Document, ...]:
    root = Path(directory)
    if not root.is_dir():
        raise CorpusLoadError(["KB_DIR: каталог не существует"])
    paths = sorted(root.rglob("*.md"))
    if not paths:
        raise CorpusLoadError(["KB_DIR: нет документов Markdown"])
    documents, issues, ids = [], [], set()
    for path in paths:
        name = path.relative_to(root).as_posix()
        try:
            if path.is_symlink() or any((root / p).is_symlink() for p in path.relative_to(root).parents if p != Path('.')):
                raise DocumentError("символические ссылки не поддерживаются")
            document = parse_document(path.read_text(encoding="utf-8"), filename=path.name)
            if document.doc_id in ids:
                raise DocumentError("повторяющийся id документа")
            ids.add(document.doc_id)
            documents.append(document)
        except (OSError, UnicodeError) as exc:
            issues.append(f"{name}: невозможно прочитать UTF-8 файл ({type(exc).__name__})")
        except DocumentError as exc:
            issues.append(f"{name}: {exc}")
    if issues:
        raise CorpusLoadError(issues)
    return tuple(documents)
