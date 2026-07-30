"""HTTP API for Enterprise RAG System."""

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse

from enterprise_rag_system.answer_eval import build_answer_judge
from enterprise_rag_system.evaluation import (
    DEFAULT_EVAL_DATASET,
    RetrievalEvaluator,
    load_eval_dataset,
)
from enterprise_rag_system.ingestion import chunk_documents, load_jsonl
from enterprise_rag_system.models import (
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
    BatchEvaluationRequest,
    BatchEvaluationResponse,
    EvaluationRequest,
    EvaluationResponse,
    QueryRequest,
    QueryResponse,
)
from enterprise_rag_system.pipeline import RAGPipeline

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DOCS = ROOT / "data" / "sample" / "policies.jsonl"


def build_pipeline() -> RAGPipeline:
    """Build an in-memory pipeline from sample docs."""
    docs = load_jsonl(SAMPLE_DOCS)
    chunks = chunk_documents(docs)
    return RAGPipeline(chunks)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject requests without the configured API key.

    Auth is enabled by setting ``RAG_API_KEY``; when it is unset the API stays
    open (local development). The key is read per-request so tests and
    deployments can toggle it without rebuilding the app.
    """
    expected = os.getenv("RAG_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


app = FastAPI(
    title="Enterprise RAG System",
    version="0.3.0",
    description="Hybrid RAG with citations, reranking and retrieval evaluation.",
)
pipeline = build_pipeline()
evaluator = RetrievalEvaluator(pipeline)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
def query(request: QueryRequest) -> QueryResponse:
    return pipeline.query(request.question, top_k=request.top_k)


@app.post("/evaluate", response_model=EvaluationResponse, dependencies=[Depends(require_api_key)])
def evaluate(request: EvaluationRequest) -> EvaluationResponse:
    return evaluator.evaluate(request.question, request.relevant_doc_ids, top_k=request.top_k)


@app.post(
    "/evaluate/batch",
    response_model=BatchEvaluationResponse,
    dependencies=[Depends(require_api_key)],
)
def evaluate_batch(request: BatchEvaluationRequest) -> BatchEvaluationResponse:
    dataset_path = Path(os.getenv("RAG_EVAL_DATASET", str(DEFAULT_EVAL_DATASET)))
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Eval dataset not found: {dataset_path.name}")
    examples = load_eval_dataset(dataset_path)
    return evaluator.evaluate_batch(examples, top_k=request.top_k, dataset_name=dataset_path.stem)


@app.post(
    "/evaluate/answer",
    response_model=AnswerEvaluationResponse,
    dependencies=[Depends(require_api_key)],
)
def evaluate_answer(request: AnswerEvaluationRequest) -> AnswerEvaluationResponse:
    """Answer the question, then judge the answer against its own context.

    The judge is selected per-request from ``RAG_JUDGE_MODE`` so deployments
    can switch between the heuristic and LLM judges without a restart.
    """
    query_response = pipeline.query(request.question, top_k=request.top_k)
    judge = build_answer_judge()
    judgement = judge.judge(request.question, query_response.answer, query_response.results)
    return AnswerEvaluationResponse(judgement=judgement, query=query_response)
