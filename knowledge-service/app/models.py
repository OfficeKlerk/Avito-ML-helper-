"""Immutable knowledge objects; serializers match contracts E and common.Source."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    visibility: tuple[str, ...]
    tags: tuple[str, ...]
    updated_at: str
    disclaimer: str
    text: str

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id, "title": self.title,
            "visibility": list(self.visibility), "tags": list(self.tags),
            "updated_at": self.updated_at, "disclaimer": self.disclaimer,
            "text": self.text,
        }


@dataclass(frozen=True)
class Chunk:
    document: Document
    anchor: str
    section: str
    text: str
    # 1-based inclusive range in Document.text, including the section heading.
    start_line: int
    end_line: int

    @property
    def chunk_id(self) -> str:
        return f"{self.document.doc_id}#{self.anchor}"

    @property
    def source(self) -> dict:
        return {
            "doc_id": self.document.doc_id, "chunk_id": self.chunk_id,
            "title": self.document.title, "section": self.section,
        }

    def to_result(self, score: float) -> dict:
        """K4 supplies a real relevance score; no ranking is invented here."""
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
            raise ValueError("score must be a finite non-negative number")
        return {
            "source": self.source, "text": self.text, "score": score,
            "updated_at": self.document.updated_at, "disclaimer": self.document.disclaimer,
        }
