"""K2: section anchors, not positions or text hashes, identify chunks."""

from __future__ import annotations

import re

from .loader import DocumentError
from .models import Chunk, Document

SECTION = re.compile(r"^ {0,3}##\s+(.+?)\s+\{#([a-z0-9_-]+)\}\s*$")
HEADING = re.compile(r"^ {0,3}##(?:\s|$)")
TITLE = re.compile(r"^ {0,3}#\s+\S.*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def chunk_document(document: Document) -> tuple[Chunk, ...]:
    lines = document.text.splitlines()
    sections: list[tuple[int, str, str]] = []
    anchors = set()
    fence: str | None = None
    title_seen = False
    for index, line in enumerate(lines):
        marker = FENCE.match(line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            if not sections:
                raise DocumentError("текст до первого раздела должен находиться под заголовком с якорем")
            fence = marker[1]
            continue
        section = SECTION.fullmatch(line)
        if section:
            title, anchor = section.groups()
            if not title.strip():
                raise DocumentError(f"строка {index + 1}: пустой заголовок раздела")
            if anchor in anchors:
                raise DocumentError(f"строка {index + 1}: повторяющийся якорь")
            anchors.add(anchor)
            sections.append((index, title.strip(), anchor))
        elif HEADING.match(line):
            raise DocumentError(f"строка {index + 1}: разделу нужен якорь {{#anchor}}")
        elif not sections and line.strip():
            if not title_seen and TITLE.fullmatch(line):
                title_seen = True
            else:
                raise DocumentError("текст до первого раздела должен находиться под заголовком с якорем")
    if fence:
        raise DocumentError("не закрыт блок кода")
    if not sections:
        raise DocumentError("нет разделов с якорями")
    chunks = []
    for position, (start, title, anchor) in enumerate(sections):
        end = sections[position + 1][0] if position + 1 < len(sections) else len(lines)
        text = "\n".join(lines[start + 1:end]).strip()
        if not text:
            raise DocumentError(f"строка {start + 1}: пустой раздел")
        chunks.append(Chunk(document, anchor, title, text, start + 1, end))
    return tuple(chunks)
