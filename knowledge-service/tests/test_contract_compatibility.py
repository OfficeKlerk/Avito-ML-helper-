"""Real corpus → current schemas and fixture source identifiers (no search mock)."""

import json

from app.chunking import chunk_document
from app.loader import load_documents
from conftest import DATA, FIXTURES, validate


def test_every_real_document_and_chunk_matches_shared_contract(registry):
    count = 0
    for document in load_documents(DATA / "kb"):
        validate(document.to_dict(), "e_knowledge.yaml#/components/schemas/Document", registry)
        for chunk in chunk_document(document):
            validate(chunk.source, "common.yaml#/components/schemas/Source", registry)
            validate(chunk.to_result(0.5), "e_knowledge.yaml#/components/schemas/Chunk", registry)
            count += 1
    assert count >= 29


def test_existing_agent_and_knowledge_sources_keep_the_same_ids_and_titles():
    actual = {
        chunk.chunk_id: chunk.source
        for document in load_documents(DATA / "kb") for chunk in chunk_document(document)
    }
    def sources(value):
        if isinstance(value, dict):
            if "doc_id" in value and "chunk_id" in value and "title" in value:
                yield value
            else:
                for child in value.values():
                    yield from sources(child)
        elif isinstance(value, list):
            for child in value:
                yield from sources(child)
    seen = set()
    for directory in ["b_agent", "e_knowledge"]:
        for path in sorted((FIXTURES / directory).glob("*.json")):
            for source in sources(json.loads(path.read_text())):
                expected = actual[source["chunk_id"]]
                assert source == {k: expected[k] for k in source}, (path.name, source)
                seen.add(source["chunk_id"])
    assert "kb_absence_rules#day-off" in seen
    assert "kb_delivery_rituals#standup" in seen
