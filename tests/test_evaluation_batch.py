"""Batch evaluation tests."""

from pathlib import Path

import pytest

from enterprise_rag_system.embeddings import HashingEmbedder
from enterprise_rag_system.evaluation import (
    DEFAULT_EVAL_DATASET,
    RetrievalEvaluator,
    load_eval_dataset,
)
from enterprise_rag_system.ingestion import chunk_documents, load_jsonl
from enterprise_rag_system.pipeline import RAGPipeline
from enterprise_rag_system.vector_store import InMemoryVectorStore


ROOT = Path(__file__).resolve().parents[1]


def _evaluator() -> RetrievalEvaluator:
    docs = load_jsonl(ROOT / "data" / "sample" / "policies.jsonl")
    pipeline = RAGPipeline(
        chunk_documents(docs),
        embedder=HashingEmbedder(),
        vector_store=InMemoryVectorStore(),
    )
    return RetrievalEvaluator(pipeline)


def test_load_eval_dataset_parses_labeled_queries():
    examples = load_eval_dataset(DEFAULT_EVAL_DATASET)

    assert len(examples) == 10
    assert all(example.relevant_doc_ids for example in examples)
    assert examples[0].query_id == "q01"


def test_evaluate_batch_aggregates_metrics():
    examples = load_eval_dataset(DEFAULT_EVAL_DATASET)
    report = _evaluator().evaluate_batch(examples, top_k=1, dataset_name="retrieval_v1")

    assert report.dataset == "retrieval_v1"
    assert report.example_count == 10
    assert len(report.per_query) == 10
    assert 0.0 <= report.mean_recall_at_k <= 1.0
    assert 0.0 <= report.mean_mrr <= 1.0
    # The bundled dataset is easy for hybrid retrieval by design: the right
    # document should be ranked first for the large majority of queries.
    assert report.mean_mrr >= 0.8


def test_evaluate_batch_rejects_empty_dataset():
    with pytest.raises(ValueError, match="empty"):
        _evaluator().evaluate_batch([], top_k=3)
