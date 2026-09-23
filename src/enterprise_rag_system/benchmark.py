"""Offline retrieval ablations with versioned data and regression checks.

Run ``python -m enterprise_rag_system.benchmark --help`` for the CLI.
No answer generation, external vector stores or provider credentials are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from math import ceil, log2
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag_system.cross_encoder import (
    DEFAULT_CE_MODEL,
    DEFAULT_CE_REVISION,
    CrossEncoderReranker,
)
from enterprise_rag_system.embeddings import (
    DEFAULT_ST_MODEL,
    DEFAULT_ST_REVISION,
    Embedder,
    HashingEmbedder,
    SentenceTransformerEmbedder,
    TfidfEmbedder,
)
from enterprise_rag_system.generation import DeterministicAnswerGenerator
from enterprise_rag_system.ingestion import chunk_documents, load_jsonl
from enterprise_rag_system.pipeline import RAGPipeline
from enterprise_rag_system.retrieval import RetrievalMode
from enterprise_rag_system.vector_store import InMemoryVectorStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "benchmarks" / "corporate_pt_v1"
Backend = Literal["hashing", "tfidf", "sentence-transformer"]
BACKENDS: tuple[str, ...] = ("hashing", "tfidf", "sentence-transformer")
# Rerank: False, the legacy title bonus (True) or the optional cross-encoder.
Rerank = bool | Literal["cross-encoder"]
# First-stage candidates the cross-encoder reorders.
CROSS_ENCODER_POOL = 20
STRATEGIES: tuple[tuple[str, RetrievalMode, Rerank], ...] = (
    ("lexical", "lexical", False),
    ("vector", "vector", False),
    ("hybrid", "hybrid", False),
    ("hybrid-rerank", "hybrid", True),
)
DEFAULT_STRATEGIES = tuple(name for name, _, _ in STRATEGIES)
EXPERIMENTAL_STRATEGIES: tuple[tuple[str, RetrievalMode, Rerank], ...] = (
    ("bm25", "bm25", False),
    ("rrf", "rrf", False),
    # Require the ``semantic`` extra (cross-encoder weights download once).
    ("bm25-ce", "bm25", "cross-encoder"),
    ("rrf-ce", "rrf", "cross-encoder"),
)
STRATEGY_OPTIONS = {name: (mode, rerank) for name, mode, rerank in (
    *STRATEGIES, *EXPERIMENTAL_STRATEGIES,
)}


class BenchmarkCase(BaseModel):
    query_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    relevant_doc_ids: list[str]
    split: Literal["dev", "test"]
    category: str = Field(min_length=1)


class RankingMetrics(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    recall: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    ndcg: float = Field(ge=0, le=1)


class CaseResult(BaseModel):
    query_id: str
    category: str
    relevant_doc_ids: list[str]
    retrieved_doc_ids: list[str]
    metrics: RankingMetrics | None


class BenchmarkRow(BaseModel):
    strategy: str
    top_k: int
    answerable_count: int
    unanswerable_count: int
    mean_metrics: RankingMetrics | None
    # A retrieval diagnostic, NOT a hallucination or answer correctness metric.
    unanswerable_return_rate: float | None
    latency_median_ms: float
    latency_p95_ms: float
    per_query: list[CaseResult]


class BenchmarkReport(BaseModel):
    schema_version: Literal[1] = 1
    corpus_sha256: str
    queries_sha256: str
    split: Literal["dev", "test"]
    embedding_backend: Backend
    max_words: int
    repeats: int
    document_count: int
    chunk_count: int
    query_count: int
    index_ms: float
    environment: dict[str, str]
    rows: list[BenchmarkRow]


def ranking_metrics(
    retrieved_doc_ids: list[str], relevant_doc_ids: list[str], top_k: int
) -> RankingMetrics | None:
    """Binary relevance at chunk positions; repeated documents get no extra gain.

    K counts retrieved chunks, matching the API. Duplicate documents retain
    their rank slots but receive zero gain after their first relevant hit.
    Unanswerable queries have undefined recall/nDCG and are reported separately.
    """
    if top_k < 1:
        raise ValueError("top_k must be positive")
    relevant = set(relevant_doc_ids)
    if not relevant:
        return None
    seen: set[str] = set()
    gains = []
    for doc_id in retrieved_doc_ids[:top_k]:
        gains.append(int(doc_id in relevant and doc_id not in seen))
        seen.add(doc_id)
    dcg = sum(gain / log2(rank + 1) for rank, gain in enumerate(gains, 1))
    ideal = sum(1 / log2(rank + 1) for rank in range(1, min(top_k, len(relevant)) + 1))
    return RankingMetrics(
        recall=sum(gains) / len(relevant),
        precision=sum(gains) / top_k,
        mrr=next((1 / rank for rank, gain in enumerate(gains, 1) if gain), 0.0),
        ndcg=dcg / ideal,
    )


def load_cases(path: Path, document_ids: set[str]) -> list[BenchmarkCase]:
    cases = [
        BenchmarkCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for case in cases:
        question = " ".join(case.question.casefold().split())
        if not question or case.query_id in seen_ids or question in seen_questions:
            raise ValueError(f"Empty or duplicate query: {case.query_id}")
        if len(case.relevant_doc_ids) != len(set(case.relevant_doc_ids)):
            raise ValueError(f"Duplicate relevance labels: {case.query_id}")
        unknown = set(case.relevant_doc_ids) - document_ids
        if unknown:
            raise ValueError(f"Unknown document labels for {case.query_id}: {sorted(unknown)}")
        seen_ids.add(case.query_id)
        seen_questions.add(question)
    return cases


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_sha256() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _build_embedder(backend: Backend, st_model: str, st_revision: str | None) -> Embedder:
    if backend == "hashing":
        return HashingEmbedder()
    if backend == "tfidf":
        return TfidfEmbedder()
    return SentenceTransformerEmbedder(st_model, st_revision)


def _installed(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def run_benchmark(
    corpus: Path, queries: Path, *, split: Literal["dev", "test"] = "dev",
    backend: Backend = "hashing", top_ks: tuple[int, ...] = (1, 3, 5),
    repeats: int = 5, max_words: int = 80,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    st_model: str = DEFAULT_ST_MODEL, st_revision: str | None = DEFAULT_ST_REVISION,
    ce_model: str = DEFAULT_CE_MODEL, ce_revision: str | None = DEFAULT_CE_REVISION,
    embedder: Embedder | None = None, cross_encoder: CrossEncoderReranker | None = None,
) -> BenchmarkReport:
    """Run the retrieval ablations.

    ``embedder`` / ``cross_encoder`` inject prebuilt backends (tests, notebooks);
    otherwise they are built from ``backend`` and the pinned model revisions.
    """
    if repeats < 1 or max_words < 1 or not top_ks or any(k < 1 for k in top_ks):
        raise ValueError("repeats, max_words and top_ks must be positive")
    if backend not in BACKENDS:
        raise ValueError(f"Unknown embedding backend: {backend}")
    if (not strategies or len(set(strategies)) != len(strategies)
            or any(name not in STRATEGY_OPTIONS for name in strategies)):
        raise ValueError("Strategies must be non-empty, unique and supported")
    documents = load_jsonl(corpus)
    document_ids = {doc.doc_id for doc in documents}
    if not documents or len(document_ids) != len(documents):
        raise ValueError("Corpus must be non-empty with unique document ids")
    if any(not doc.text.strip() or not doc.doc_id.strip() for doc in documents):
        raise ValueError("Corpus documents need non-empty ids and text")
    cases = [case for case in load_cases(queries, document_ids) if case.split == split]
    if not cases:
        raise ValueError(f"No queries in split {split!r}")
    uses_cross_encoder = any(
        STRATEGY_OPTIONS[name][1] == "cross-encoder" for name in strategies
    )
    if uses_cross_encoder and cross_encoder is None:
        cross_encoder = CrossEncoderReranker(ce_model, ce_revision)
    started = perf_counter()
    chunks = chunk_documents(documents, max_words=max_words)
    if embedder is None:
        embedder = _build_embedder(backend, st_model, st_revision)
    pipeline = RAGPipeline(
        chunks,
        answer_generator=DeterministicAnswerGenerator(),
        embedder=embedder,
        vector_store=InMemoryVectorStore(),
    )
    index_ms = (perf_counter() - started) * 1000
    def retrieve(question: str, top_k: int, mode: RetrievalMode, rerank: Rerank):
        if rerank != "cross-encoder":
            return pipeline.retrieve(question, top_k, mode=mode, rerank=bool(rerank))
        assert cross_encoder is not None
        pool = pipeline.retrieve(
            question, max(top_k, CROSS_ENCODER_POOL), mode=mode, rerank=False
        )
        return cross_encoder.rerank(question, pool)[:top_k]

    rows = []
    for strategy in strategies:
        mode, rerank = STRATEGY_OPTIONS[strategy]
        for top_k in sorted(set(top_ks)):
            durations = []
            results = []
            for case in cases:
                # One warmup per query/configuration, excluded from latency.
                retrieve(case.question, top_k, mode, rerank)
                for repeat in range(repeats):
                    started = perf_counter()
                    retrieved = retrieve(case.question, top_k, mode, rerank)
                    durations.append((perf_counter() - started) * 1000)
                    if repeat == 0:
                        ids = [result.chunk.doc_id for result in retrieved]
                        results.append(CaseResult(
                            query_id=case.query_id, category=case.category,
                            relevant_doc_ids=case.relevant_doc_ids, retrieved_doc_ids=ids,
                            metrics=ranking_metrics(ids, case.relevant_doc_ids, top_k),
                        ))
            metrics = [r.metrics for r in results if r.metrics is not None]
            unanswerable = [r for r in results if r.metrics is None]
            rows.append(BenchmarkRow(
                strategy=strategy, top_k=top_k,
                answerable_count=len(metrics), unanswerable_count=len(unanswerable),
                mean_metrics=RankingMetrics(**{
                    field: mean(getattr(m, field) for m in metrics)
                    for field in RankingMetrics.model_fields
                }) if metrics else None,
                unanswerable_return_rate=(
                    mean(bool(r.retrieved_doc_ids) for r in unanswerable) if unanswerable else None
                ),
                latency_median_ms=median(durations),
                latency_p95_ms=sorted(durations)[ceil(0.95 * len(durations)) - 1],
                per_query=results,
            ))
    return BenchmarkReport(
        corpus_sha256=_sha256(corpus), queries_sha256=_sha256(queries),
        split=split, embedding_backend=backend, max_words=max_words, repeats=repeats,
        document_count=len(documents), chunk_count=len(chunks), query_count=len(cases),
        index_ms=index_ms,
        environment={
            "python": platform.python_version(), "platform": platform.platform(),
            "machine": platform.machine(), "source_sha256": _source_sha256(),
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "embedding_dimensions": str(getattr(embedder, "dims", "unknown")),
            "embedding_model": getattr(embedder, "model_name", backend),
            "embedding_revision": str(getattr(embedder, "revision", "not-applicable")),
            "cross_encoder_model": cross_encoder.model_name if cross_encoder else "not-used",
            "cross_encoder_revision": (
                str(cross_encoder.revision) if cross_encoder else "not-used"
            ),
            "pydantic": version("pydantic"),
            "scikit-learn": version("scikit-learn") if backend == "tfidf" else "not-used",
            "numpy": _installed("numpy") if backend != "hashing" else "not-used",
            "sentence-transformers": (
                _installed("sentence-transformers")
                if backend == "sentence-transformer" or cross_encoder else "not-used"
            ),
            "torch": (
                _installed("torch")
                if backend == "sentence-transformer" or cross_encoder else "not-used"
            ),
        },
        rows=rows,
    )


def compare_reports(
    current: BenchmarkReport, baseline: BenchmarkReport, max_regression: float = 0.0
) -> list[str]:
    """Fail closed on incomparable data/configurations; never gate machine latency."""
    if not 0 <= max_regression <= 1:
        raise ValueError("max_regression must be between 0 and 1")
    for field in (
        "corpus_sha256", "queries_sha256", "split", "embedding_backend", "max_words",
        "document_count", "query_count",
    ):
        if getattr(current, field) != getattr(baseline, field):
            raise ValueError(f"Incomparable benchmark field: {field}")
    # Different weights are a different system, even under the same backend name.
    for env_key in ("embedding_model", "embedding_revision",
                "cross_encoder_model", "cross_encoder_revision"):
        if current.environment.get(env_key) != baseline.environment.get(env_key):
            raise ValueError(f"Incomparable benchmark environment: {env_key}")
    expected = {(r.strategy, r.top_k): r for r in baseline.rows}
    actual = {(r.strategy, r.top_k): r for r in current.rows}
    if set(expected) != set(actual) or len(expected) != len(baseline.rows):
        raise ValueError("Benchmark strategy/K matrix differs or contains duplicates")
    if len(actual) != len(current.rows):
        raise ValueError("Duplicate current benchmark rows")
    failures = []
    for key, before in expected.items():
        after = actual[key]
        before_cases = [(r.query_id, r.relevant_doc_ids) for r in before.per_query]
        after_cases = [(r.query_id, r.relevant_doc_ids) for r in after.per_query]
        if before_cases != after_cases:
            raise ValueError("Benchmark queries or relevance labels differ")
        if (before.mean_metrics is None) != (after.mean_metrics is None):
            raise ValueError("Answerable query population changed")
        if before.mean_metrics is not None and after.mean_metrics is not None:
            for field in RankingMetrics.model_fields:
                old = getattr(before.mean_metrics, field)
                new = getattr(after.mean_metrics, field)
                if new + max_regression + 1e-12 < old:
                    failures.append(f"{key[0]}@{key[1]} {field}: {old:.6f} -> {new:.6f}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_DATA / "corpus.jsonl")
    parser.add_argument("--queries", type=Path, default=DEFAULT_DATA / "queries.jsonl")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--backend", choices=BACKENDS, default="hashing")
    parser.add_argument("--top-k", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--max-words", type=int, default=80)
    parser.add_argument("--strategies", nargs="+", choices=tuple(STRATEGY_OPTIONS),
                        default=list(DEFAULT_STRATEGIES))
    parser.add_argument("--st-model", default=DEFAULT_ST_MODEL)
    parser.add_argument("--st-revision", default=DEFAULT_ST_REVISION,
                        help="Hugging Face commit; 'latest' disables pinning")
    parser.add_argument("--ce-model", default=DEFAULT_CE_MODEL)
    parser.add_argument("--ce-revision", default=DEFAULT_CE_REVISION,
                        help="Hugging Face commit; 'latest' disables pinning")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-regression", type=float, default=0.0)
    args = parser.parse_args()
    try:
        report = run_benchmark(
            args.corpus, args.queries, split=args.split, backend=args.backend,
            top_ks=tuple(args.top_k), repeats=args.repeats, max_words=args.max_words,
            strategies=tuple(args.strategies),
            st_model=args.st_model,
            st_revision=None if args.st_revision == "latest" else args.st_revision,
            ce_model=args.ce_model,
            ce_revision=None if args.ce_revision == "latest" else args.ce_revision,
        )
        output = report.model_dump_json(indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # LF on every platform, so reports diff cleanly and match .gitattributes.
            args.output.write_text(output, encoding="utf-8", newline="\n")
        else:
            print(output, end="")
        if args.baseline:
            baseline = BenchmarkReport.model_validate_json(
                args.baseline.read_text(encoding="utf-8")
            )
            failures = compare_reports(report, baseline, args.max_regression)
            if failures:
                parser.exit(1, "Retrieval regression:\n" + "\n".join(failures) + "\n")
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Benchmark error: {exc}\n")


if __name__ == "__main__":
    main()
