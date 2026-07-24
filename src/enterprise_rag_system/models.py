"""Typed contracts for retrieval, answer generation and evaluation."""

from typing import Dict, List, Union
from pydantic import BaseModel, Field


class Document(BaseModel):
    """Raw source document."""

    doc_id: str
    title: str
    text: str


class Chunk(BaseModel):
    """Searchable document chunk."""

    chunk_id: str
    doc_id: str
    title: str
    text: str


class SearchResult(BaseModel):
    """Retrieved chunk with transparent score components."""

    chunk: Chunk
    lexical_score: float
    vector_score: float
    hybrid_score: float
    rerank_score: float = 0.0


class Citation(BaseModel):
    """Citation returned with an answer."""

    doc_id: str
    title: str
    chunk_id: str


class QueryRequest(BaseModel):
    """Question submitted to the RAG API."""

    question: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class QueryResponse(BaseModel):
    """Grounded answer and retrieval metadata."""

    answer: str
    citations: List[Citation]
    results: List[SearchResult]
    metadata: Dict[str, Union[float, int, str]]


class EvaluationRequest(BaseModel):
    """Evaluation request with known relevant documents."""

    question: str = Field(min_length=1)
    relevant_doc_ids: List[str] = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class EvaluationResponse(BaseModel):
    """Retrieval quality metrics."""

    recall_at_k: float
    mrr: float
    retrieved_doc_ids: List[str]
    query: QueryResponse


class EvalExample(BaseModel):
    """One labeled query from a versioned evaluation dataset."""

    query_id: str
    question: str = Field(min_length=1)
    relevant_doc_ids: List[str] = Field(min_length=1)


class QueryMetrics(BaseModel):
    """Per-query metrics inside a batch evaluation."""

    query_id: str
    question: str
    recall_at_k: float
    mrr: float
    retrieved_doc_ids: List[str]


class BatchEvaluationRequest(BaseModel):
    """Batch evaluation over the bundled labeled dataset."""

    top_k: int = Field(default=3, ge=1, le=10)


class BatchEvaluationResponse(BaseModel):
    """Aggregate retrieval quality over a labeled dataset."""

    dataset: str
    example_count: int
    top_k: int
    mean_recall_at_k: float
    mean_mrr: float
    per_query: List[QueryMetrics]


class AnswerJudgement(BaseModel):
    """Faithfulness verdict for one generated answer."""

    faithfulness: float = Field(ge=0.0, le=1.0)
    unsupported_claims: List[str]
    judge_mode: str


class AnswerEvaluationRequest(BaseModel):
    """Run a query and judge the generated answer against its own context."""

    question: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class AnswerEvaluationResponse(BaseModel):
    """Answer-quality metrics alongside the full query response."""

    judgement: AnswerJudgement
    query: QueryResponse
