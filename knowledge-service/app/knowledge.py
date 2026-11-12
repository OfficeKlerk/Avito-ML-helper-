"""Loaded corpus and request-scoped, authorized input for K4 search and K5 API."""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from types import MappingProxyType

from flask import current_app, request

from .access import KnowledgeAccessError, Principal, authenticate, can_read
from .chunking import chunk_document
from .loader import CorpusLoadError, DocumentError, load_documents
from .models import Chunk, Document
from .search import SearchIndex


class KnowledgeUnavailableError(Exception):
    pass


class KnowledgeView:
    """A snapshot for ONE authenticated user. Build retrieval indexes from chunks()."""

    def __init__(self, documents: tuple[Document, ...], chunks: tuple[Chunk, ...], principal: Principal, index_factory=None):
        self._index_factory = index_factory
        self._known_ids = frozenset(document.doc_id for document in documents)
        self._documents = MappingProxyType({
            document.doc_id: document for document in documents if can_read(document.visibility, principal)
        })
        self._chunks = tuple(chunk for chunk in chunks if chunk.document.doc_id in self._documents)

    def documents(self) -> tuple[Document, ...]:
        return tuple(self._documents.values())

    def chunks(self) -> tuple[Chunk, ...]:
        return self._chunks

    def document(self, doc_id: str) -> Document:
        if doc_id in self._documents:
            return self._documents[doc_id]
        raise KnowledgeAccessError(403 if doc_id in self._known_ids else 404)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        index = self._index_factory(tuple(self._documents)) if self._index_factory else SearchIndex(self._chunks)
        return index.search(query, top_k)


class KnowledgeBase:
    def __init__(self, documents: tuple[Document, ...], chunks: tuple[Chunk, ...]):
        self._documents = documents
        self._chunks = chunks
        # Cache only identical allowed document sets; bounded independently of user count.
        self._search_index = lru_cache(maxsize=64)(self._build_search_index)

    def _build_search_index(self, allowed_ids: tuple[str, ...]) -> SearchIndex:
        allowed = frozenset(allowed_ids)
        return SearchIndex(tuple(chunk for chunk in self._chunks if chunk.document.doc_id in allowed))

    @classmethod
    def load(cls, directory: str | Path) -> KnowledgeBase:
        documents = load_documents(directory)
        chunks, issues = [], []
        for document in documents:
            try:
                chunks.extend(chunk_document(document))
            except DocumentError as exc:
                issues.append(f"{document.doc_id}.md: {exc}")
        if issues:
            raise CorpusLoadError(issues)
        return cls(documents, tuple(chunks))

    def authorize(self, authorization: str | None, *, jwt_secret: str) -> KnowledgeView:
        principal = authenticate(authorization, jwt_secret)
        return KnowledgeView(self._documents, self._chunks, principal, self._search_index)


def knowledge_for_request() -> KnowledgeView:
    """K5 handlers use this adapter; no user/role/team fields are read from JSON."""
    knowledge = current_app.extensions.get("knowledge_base")
    if knowledge is None:
        authenticate(request.headers.get("Authorization"), current_app.config["JWT_SECRET"])
        raise KnowledgeUnavailableError
    return knowledge.authorize(
        request.headers.get("Authorization"), jwt_secret=current_app.config["JWT_SECRET"],
    )
