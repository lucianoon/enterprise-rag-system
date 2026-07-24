"""Embedding backend tests."""

import hashlib
from math import sqrt

import pytest

from enterprise_rag_system.embeddings import (
    HashingEmbedder,
    build_embedder,
)


def test_hashing_embedder_is_deterministic_across_instances():
    a = HashingEmbedder()
    b = HashingEmbedder()

    assert a.embed_query("refund policy approval") == b.embed_query("refund policy approval")


def test_hashing_embedder_uses_stable_buckets_not_builtin_hash():
    embedder = HashingEmbedder(dims=48)
    expected = int.from_bytes(hashlib.md5(b"refund").digest()[:8], "big") % 48

    assert embedder._bucket("refund") == expected


def test_hashing_embedder_returns_unit_vectors():
    vector = HashingEmbedder().embed_query("employees must redact sensitive data")
    norm = sqrt(sum(v * v for v in vector))

    assert norm == pytest.approx(1.0)


def test_build_embedder_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "word2vec")

    with pytest.raises(ValueError, match="RAG_EMBEDDING_BACKEND"):
        build_embedder()


def test_build_embedder_defaults_to_hashing(monkeypatch):
    monkeypatch.delenv("RAG_EMBEDDING_BACKEND", raising=False)

    assert build_embedder().name == "hashing"


def test_tfidf_embedder_ranks_related_document_first():
    sklearn = pytest.importorskip("sklearn")  # noqa: F841
    from enterprise_rag_system.embeddings import TfidfEmbedder

    corpus = [
        "Refund requests require the order ID and purchase date.",
        "Employees must not paste credit card numbers into AI tools.",
        "Enterprise customers receive support responses within two hours.",
    ]
    embedder = TfidfEmbedder()
    embedder.fit(corpus)
    doc_vectors = embedder.embed_texts(corpus)
    query = embedder.embed_query("refund order purchase")

    scores = [sum(q * d for q, d in zip(query, doc)) for doc in doc_vectors]

    assert scores.index(max(scores)) == 0
