"""Vector store backend tests."""

import pytest

from enterprise_rag_system.vector_store import InMemoryVectorStore, build_vector_store


def test_in_memory_store_returns_best_match_first():
    store = InMemoryVectorStore()
    store.index(
        ["chunk_a", "chunk_b", "chunk_c"],
        [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]],
    )

    results = store.search([1.0, 0.0], top_k=2)

    assert results[0][0] == "chunk_a"
    assert results[0][1] == pytest.approx(1.0)
    assert len(results) == 2


def test_build_vector_store_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_STORE", "pinecone")

    with pytest.raises(ValueError, match="RAG_VECTOR_STORE"):
        build_vector_store()


def test_build_vector_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("RAG_VECTOR_STORE", raising=False)

    assert build_vector_store().name == "memory"


def test_qdrant_store_round_trip_in_memory_mode():
    pytest.importorskip("qdrant_client")
    from enterprise_rag_system.vector_store import QdrantVectorStore

    store = QdrantVectorStore(url=":memory:", collection="test_chunks")
    store.index(
        ["policy_refunds:0", "policy_security:0"],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    results = store.search([0.9, 0.1, 0.0], top_k=2)

    assert results[0][0] == "policy_refunds:0"
    assert results[0][1] > results[1][1]
