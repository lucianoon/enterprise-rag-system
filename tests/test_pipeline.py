"""Pipeline tests."""

from pathlib import Path

from enterprise_rag_system.evaluation import RetrievalEvaluator
from enterprise_rag_system.ingestion import chunk_documents, load_jsonl
from enterprise_rag_system.pipeline import RAGPipeline

ROOT = Path(__file__).resolve().parents[1]


def _pipeline():
    docs = load_jsonl(ROOT / "data" / "sample" / "policies.jsonl")
    return RAGPipeline(chunk_documents(docs))


def test_query_returns_citations():
    pipeline = _pipeline()
    response = pipeline.query("What does the refund policy require?", top_k=2)

    assert response.citations
    assert response.citations[0].doc_id == "policy_refunds"
    assert "Refund Policy" in response.answer


def test_evaluator_computes_recall_and_mrr():
    evaluator = RetrievalEvaluator(_pipeline())
    result = evaluator.evaluate(
        "What is the SLA for high priority support tickets?",
        relevant_doc_ids=["policy_sla"],
        top_k=3,
    )

    assert result.recall_at_k == 1.0
    assert result.mrr > 0


def test_retrieve_matches_query_evidence_without_invoking_generator(monkeypatch):
    pipeline = _pipeline()
    expected = pipeline.query("refund policy", top_k=2).results

    def forbidden(*args, **kwargs):
        raise AssertionError("Retrieval must not invoke generation")

    monkeypatch.setattr(pipeline.answer_generator, "compose", forbidden)

    assert pipeline.retrieve("refund policy", top_k=2) == expected



def test_bm25_pipeline_returns_same_evidence_as_retriever_without_legacy_rerank(monkeypatch):
    docs = load_jsonl(ROOT / 'data' / 'sample' / 'policies.jsonl')
    pipeline = RAGPipeline(chunk_documents(docs), retrieval_mode='bm25')

    def forbidden(*args, **kwargs):
        raise AssertionError('Legacy title bonus must not be applied to BM25 by default')

    monkeypatch.setattr(pipeline.reranker, 'rerank', forbidden)
    expected = pipeline.retriever.search('refund policy', top_k=2, mode='bm25')
    response = pipeline.query('refund policy', top_k=2)
    assert response.results == expected
    assert response.metadata['retrieval_mode'] == 'bm25'
    assert pipeline.retrieve('refund policy', top_k=2) == expected


def test_pipeline_rejects_unknown_mode():
    import pytest

    with pytest.raises(ValueError, match='Unknown retrieval mode'):
        RAGPipeline([], retrieval_mode='typo')
