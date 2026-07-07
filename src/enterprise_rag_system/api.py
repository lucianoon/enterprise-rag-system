"""HTTP API for Enterprise RAG System."""

from pathlib import Path

from fastapi import FastAPI

from enterprise_rag_system.evaluation import RetrievalEvaluator
from enterprise_rag_system.ingestion import chunk_documents, load_jsonl
from enterprise_rag_system.models import EvaluationRequest, EvaluationResponse, QueryRequest, QueryResponse
from enterprise_rag_system.pipeline import RAGPipeline


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DOCS = ROOT / "data" / "sample" / "policies.jsonl"


def build_pipeline() -> RAGPipeline:
    """Build an in-memory pipeline from sample docs."""
    docs = load_jsonl(SAMPLE_DOCS)
    chunks = chunk_documents(docs)
    return RAGPipeline(chunks)


app = FastAPI(
    title="Enterprise RAG System",
    version="0.1.0",
    description="Hybrid RAG with citations, reranking and retrieval evaluation.",
)
pipeline = build_pipeline()
evaluator = RetrievalEvaluator(pipeline)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    return pipeline.query(request.question, top_k=request.top_k)


@app.post("/evaluate", response_model=EvaluationResponse)
def evaluate(request: EvaluationRequest) -> EvaluationResponse:
    return evaluator.evaluate(request.question, request.relevant_doc_ids, top_k=request.top_k)

