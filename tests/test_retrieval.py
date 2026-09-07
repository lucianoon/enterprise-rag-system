"""Retrieval unit tests."""

import pytest

from enterprise_rag_system.embeddings import HashingEmbedder
from enterprise_rag_system.models import Chunk
from enterprise_rag_system.retrieval import HybridRetriever, Reranker, tokenize
from enterprise_rag_system.vector_store import InMemoryVectorStore

CHUNKS = [
    Chunk(
        chunk_id="policy_refunds:0",
        doc_id="policy_refunds",
        title="Refund Policy",
        text="Refund requests must include the order ID and purchase date.",
    ),
    Chunk(
        chunk_id="policy_security:0",
        doc_id="policy_security",
        title="Security Policy",
        text="Employees must not paste credit card numbers into AI tools.",
    ),
]


def _retriever() -> HybridRetriever:
    return HybridRetriever(CHUNKS, embedder=HashingEmbedder(), vector_store=InMemoryVectorStore())


def test_tokenize_normalizes_case_and_punctuation():
    assert tokenize("Refund POLICY, v2!") == ["refund", "policy", "v2"]


def test_search_ranks_lexically_matching_chunk_first():
    results = _retriever().search("What must a refund request include?", top_k=2)

    assert results[0].chunk.doc_id == "policy_refunds"
    assert results[0].hybrid_score > results[1].hybrid_score
    assert results[0].lexical_score > 0
    assert results[0].vector_score > 0


def test_search_handles_query_without_matches():
    results = _retriever().search("zzz qqq xxx", top_k=2)

    assert len(results) == 2
    assert all(r.lexical_score == 0 for r in results)


def test_reranker_boosts_exact_title_mention():
    results = _retriever().search("security policy for AI tools", top_k=2)
    reranked = Reranker().rerank("security policy for AI tools", results)

    assert reranked[0].chunk.doc_id == "policy_security"
    assert reranked[0].rerank_score > reranked[0].hybrid_score


def test_lexical_ablation_does_not_query_vector_store(monkeypatch):
    retriever = _retriever()

    def forbidden(*args, **kwargs):
        pytest.fail("Lexical retrieval queried the vector store")

    monkeypatch.setattr(retriever.vector_store, "search", forbidden)
    results = retriever.search("refund", mode="lexical")

    assert results[0].chunk.doc_id == "policy_refunds"
    assert all(r.vector_score == 0 and r.hybrid_score == r.lexical_score for r in results)


def test_vector_ablation_does_not_use_lexical_scores(monkeypatch):
    retriever = _retriever()

    def forbidden(*args, **kwargs):
        pytest.fail("Vector retrieval invoked lexical scoring")

    monkeypatch.setattr(retriever, "_lexical_score", forbidden)
    results = retriever.search("refund", mode="vector")

    assert all(r.lexical_score == 0 and r.hybrid_score == r.vector_score for r in results)


def test_search_rejects_unknown_modes_and_nonpositive_cutoffs():
    with pytest.raises(ValueError, match="mode"):
        _retriever().search("refund", mode="unknown")
    with pytest.raises(ValueError, match="positive"):
        _retriever().search("refund", top_k=0)


def test_bm25_skips_vector_query_and_zero_match_padding(monkeypatch):
    retriever = _retriever()

    def forbidden(*args, **kwargs):
        pytest.fail('BM25 must not query the vector backend')

    monkeypatch.setattr(retriever.embedder, 'embed_query', forbidden)
    monkeypatch.setattr(retriever.vector_store, 'search', forbidden)
    assert [r.chunk.doc_id for r in retriever.search('refund', mode='bm25')] == ['policy_refunds']
    assert retriever.search('zzzz', mode='bm25') == []


def test_rrf_is_invariant_to_positive_vector_score_scaling(monkeypatch):
    retriever = _retriever()
    ids = [c.chunk_id for c in CHUNKS]
    monkeypatch.setattr(
        retriever.vector_store, 'search', lambda *a, **kw: [(ids[1], 0.9), (ids[0], 0.3)]
    )
    first = retriever.search('refund', mode='rrf')
    monkeypatch.setattr(
        retriever.vector_store, 'search', lambda *a, **kw: [(ids[1], 90), (ids[0], 30)]
    )
    scaled = retriever.search('refund', mode='rrf')
    assert [(r.chunk.chunk_id, r.hybrid_score) for r in first] == [
        (r.chunk.chunk_id, r.hybrid_score) for r in scaled
    ]
    assert first[0].chunk.doc_id == 'policy_refunds'


@pytest.mark.parametrize('mode', ['bm25', 'rrf'])
def test_new_modes_handle_empty_corpus_and_query(mode):
    retriever = HybridRetriever([], embedder=HashingEmbedder(), vector_store=InMemoryVectorStore())
    assert retriever.search('anything', mode=mode) == []
    assert _retriever().search('', mode=mode) == []


def test_new_mode_ties_are_independent_of_input_order():
    chunks = [Chunk(chunk_id=key, doc_id=key, title='same', text='same') for key in ['b', 'a']]
    for order in [chunks, list(reversed(chunks))]:
        retriever = HybridRetriever(
            order, embedder=HashingEmbedder(), vector_store=InMemoryVectorStore()
        )
        assert [r.chunk.chunk_id for r in retriever.search('same', mode='rrf')] == ['a', 'b']
