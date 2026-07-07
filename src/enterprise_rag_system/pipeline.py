"""End-to-end RAG pipeline."""

from time import perf_counter
from typing import Iterable, Optional
from uuid import uuid4

from enterprise_rag_system.generation import AnswerGenerator, build_answer_generator
from enterprise_rag_system.models import Chunk, Citation, QueryResponse
from enterprise_rag_system.retrieval import HybridRetriever, Reranker


class RAGPipeline:
    """Hybrid retrieval and citation-aware answer composition."""

    def __init__(self, chunks: Iterable[Chunk], answer_generator: Optional[AnswerGenerator] = None):
        self.retriever = HybridRetriever(chunks)
        self.reranker = Reranker()
        self.answer_generator = answer_generator or build_answer_generator()

    def query(self, question: str, top_k: int = 3) -> QueryResponse:
        started = perf_counter()
        initial = self.retriever.search(question, top_k=max(top_k * 2, top_k))
        results = self.reranker.rerank(question, initial)[:top_k]
        citations = [
            Citation(doc_id=r.chunk.doc_id, title=r.chunk.title, chunk_id=r.chunk.chunk_id)
            for r in results
        ]
        answer = self.answer_generator.compose(question, results)
        return QueryResponse(
            answer=answer,
            citations=citations,
            results=results,
            metadata={
                "query_id": str(uuid4()),
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "top_k": top_k,
                "result_count": len(results),
                "generation_mode": self.answer_generator.mode,
            },
        )

