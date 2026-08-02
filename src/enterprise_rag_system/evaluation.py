"""Retrieval evaluation: single labeled queries and versioned batch datasets.

Run the bundled dataset from the command line::

    python -m enterprise_rag_system.evaluation [--top-k 3] [--dataset PATH]
"""

import json
from pathlib import Path

from enterprise_rag_system.models import (
    BatchEvaluationResponse,
    EvalExample,
    EvaluationResponse,
    QueryMetrics,
)
from enterprise_rag_system.pipeline import RAGPipeline

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_DATASET = ROOT / "data" / "eval" / "retrieval_v1.jsonl"


def load_eval_dataset(path: Path) -> list[EvalExample]:
    """Load labeled queries from a JSONL dataset."""
    examples = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                examples.append(EvalExample.model_validate(json.loads(line)))
    return examples


class RetrievalEvaluator:
    """Computes Recall@K and MRR for labeled queries."""

    def __init__(self, pipeline: RAGPipeline):
        self.pipeline = pipeline

    def evaluate(
        self, question: str, relevant_doc_ids: list[str], top_k: int = 3
    ) -> EvaluationResponse:
        query = self.pipeline.query(question, top_k=top_k)
        retrieved = [citation.doc_id for citation in query.citations]
        relevant = set(relevant_doc_ids)
        hits = [doc_id for doc_id in retrieved if doc_id in relevant]
        recall = len(set(hits)) / len(relevant)
        mrr = 0.0
        for rank, doc_id in enumerate(retrieved, start=1):
            if doc_id in relevant:
                mrr = 1.0 / rank
                break
        return EvaluationResponse(
            recall_at_k=round(recall, 4),
            mrr=round(mrr, 4),
            retrieved_doc_ids=retrieved,
            query=query,
        )

    def evaluate_batch(
        self,
        examples: list[EvalExample],
        top_k: int = 3,
        dataset_name: str = "inline",
    ) -> BatchEvaluationResponse:
        """Aggregate Recall@K and MRR over a labeled dataset."""
        if not examples:
            raise ValueError("Evaluation dataset is empty.")
        per_query = []
        for example in examples:
            single = self.evaluate(example.question, example.relevant_doc_ids, top_k=top_k)
            per_query.append(
                QueryMetrics(
                    query_id=example.query_id,
                    question=example.question,
                    recall_at_k=single.recall_at_k,
                    mrr=single.mrr,
                    retrieved_doc_ids=single.retrieved_doc_ids,
                )
            )
        return BatchEvaluationResponse(
            dataset=dataset_name,
            example_count=len(per_query),
            top_k=top_k,
            mean_recall_at_k=round(sum(m.recall_at_k for m in per_query) / len(per_query), 4),
            mean_mrr=round(sum(m.mrr for m in per_query) / len(per_query), 4),
            per_query=per_query,
        )


def _main() -> None:
    import argparse

    from enterprise_rag_system.ingestion import chunk_documents, load_jsonl

    parser = argparse.ArgumentParser(description="Batch retrieval evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_EVAL_DATASET)
    parser.add_argument("--docs", type=Path, default=ROOT / "data" / "sample" / "policies.jsonl")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    pipeline = RAGPipeline(chunk_documents(load_jsonl(args.docs)))
    evaluator = RetrievalEvaluator(pipeline)
    report = evaluator.evaluate_batch(
        load_eval_dataset(args.dataset),
        top_k=args.top_k,
        dataset_name=args.dataset.stem,
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    _main()
