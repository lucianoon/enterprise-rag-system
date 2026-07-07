"""Retrieval evaluation metrics."""

from enterprise_rag_system.models import EvaluationResponse
from enterprise_rag_system.pipeline import RAGPipeline


class RetrievalEvaluator:
    """Computes Recall@K and MRR for labeled queries."""

    def __init__(self, pipeline: RAGPipeline):
        self.pipeline = pipeline

    def evaluate(self, question: str, relevant_doc_ids: list[str], top_k: int = 3) -> EvaluationResponse:
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

