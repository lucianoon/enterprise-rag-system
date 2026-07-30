"""Retrieval unit tests."""

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
