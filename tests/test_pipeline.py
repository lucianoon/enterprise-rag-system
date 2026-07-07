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

