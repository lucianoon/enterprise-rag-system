"""Optional semantic backends, exercised with fake models (no torch download in CI)."""

import json
import sys

import pytest

from enterprise_rag_system import embeddings
from enterprise_rag_system.benchmark import compare_reports, run_benchmark
from enterprise_rag_system.cross_encoder import (
    DEFAULT_CE_MODEL,
    DEFAULT_CE_REVISION,
    CrossEncoderReranker,
)
from enterprise_rag_system.embeddings import (
    DEFAULT_ST_MODEL,
    DEFAULT_ST_REVISION,
    SentenceTransformerEmbedder,
)
from enterprise_rag_system.generation import DeterministicAnswerGenerator
from enterprise_rag_system.models import Chunk
from enterprise_rag_system.pipeline import RAGPipeline
from enterprise_rag_system.tokenization import tokenize
from enterprise_rag_system.vector_store import InMemoryVectorStore


class FakeEncoder:
    """Bag of folded words over a tiny fixed vocabulary; records the raw inputs."""

    vocabulary = ("reembolso", "pedido", "ferias", "portal", "query", "passage")

    def __init__(self):
        self.inputs: list[str] = []

    def get_sentence_embedding_dimension(self):  # pre-5.x name, still supported
        return len(self.vocabulary)

    def encode(self, texts, **kwargs):
        assert kwargs["normalize_embeddings"] is True
        self.inputs.extend(texts)
        rows = []
        for text in texts:
            tokens = tokenize(text)
            row = [float(tokens.count(word)) for word in self.vocabulary]
            norm = sum(v * v for v in row) ** 0.5 or 1.0
            rows.append([v / norm for v in row])
        return rows


class FakeCrossEncoder:
    def __init__(self, favourite: str):
        self.favourite = favourite
        self.pairs: list[tuple[str, str]] = []

    def predict(self, pairs, **kwargs):
        self.pairs.extend(pairs)
        return [float(self.favourite in passage) for _, passage in pairs]


def test_e5_models_get_asymmetric_prefixes():
    model = FakeEncoder()
    embedder = SentenceTransformerEmbedder(model=model)
    assert (embedder.model_name, embedder.revision) == (DEFAULT_ST_MODEL, DEFAULT_ST_REVISION)
    embedder.embed_texts(["Reembolso do pedido"])
    embedder.embed_query("reembolso")
    assert model.inputs == ["passage: Reembolso do pedido", "query: reembolso"]
    assert embedder.dims == len(FakeEncoder.vocabulary)


def test_other_models_use_no_prefix_unless_configured():
    model = FakeEncoder()
    plain = SentenceTransformerEmbedder(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", None, model=model
    )
    plain.embed_query("pedido")
    custom = SentenceTransformerEmbedder("org/other", None, query_prefix="Q: ", model=model)
    custom.embed_query("pedido")
    assert model.inputs == ["pedido", "Q: pedido"]


def test_missing_optional_dependency_explains_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(RuntimeError, match="--extra semantic"):
        SentenceTransformerEmbedder()
    with pytest.raises(RuntimeError, match="--extra semantic"):
        CrossEncoderReranker()


def test_environment_selects_model_and_only_pins_the_default(monkeypatch):
    built = []

    class Recorder:
        def __init__(self, model_name, revision):
            built.append((model_name, revision))

    monkeypatch.setattr(embeddings, "SentenceTransformerEmbedder", Recorder)
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "sentence-transformer")
    monkeypatch.delenv("RAG_ST_MODEL", raising=False)
    monkeypatch.delenv("RAG_ST_REVISION", raising=False)
    embeddings.build_embedder()
    monkeypatch.setenv("RAG_ST_MODEL", "org/custom")
    embeddings.build_embedder()
    monkeypatch.setenv("RAG_ST_REVISION", "abc123")
    embeddings.build_embedder()
    assert built == [
        (DEFAULT_ST_MODEL, DEFAULT_ST_REVISION), ("org/custom", None), ("org/custom", "abc123"),
    ]


_CHUNKS = [
    Chunk(chunk_id="a:0", doc_id="a", title="Reembolso", text="Reembolso do pedido."),
    Chunk(chunk_id="b:0", doc_id="b", title="Férias", text="Férias pelo portal e pedido."),
    Chunk(chunk_id="c:0", doc_id="c", title="Outro", text="Pedido de compra."),
]


def test_cross_encoder_reorders_candidates_with_id_ties():
    model = FakeCrossEncoder("portal")
    reranker = CrossEncoderReranker(model=model)
    assert (reranker.model_name, reranker.revision) == (DEFAULT_CE_MODEL, DEFAULT_CE_REVISION)
    pipeline = RAGPipeline(
        _CHUNKS, answer_generator=DeterministicAnswerGenerator(),
        embedder=SentenceTransformerEmbedder(model=FakeEncoder()),
        vector_store=InMemoryVectorStore(), reranker=reranker, rerank_pool=10,
    )
    results = pipeline.retrieve("pedido", top_k=3, mode="bm25", rerank=True)
    assert [r.chunk.doc_id for r in results] == ["b", "a", "c"]
    assert [r.rerank_score for r in results] == [1.0, 0.0, 0.0]
    assert model.pairs[0][1].startswith(("Reembolso\n", "Férias\n", "Outro\n"))
    assert reranker.scores("pedido", []) == []


def test_rerank_pool_widens_the_candidates_only_when_reranking():
    seen = []

    class Spy:
        def rerank(self, question, results):
            seen.append(len(results))
            return results

    pipeline = RAGPipeline(
        _CHUNKS, answer_generator=DeterministicAnswerGenerator(),
        embedder=SentenceTransformerEmbedder(model=FakeEncoder()),
        vector_store=InMemoryVectorStore(), reranker=Spy(), rerank_pool=3,
    )
    assert len(pipeline.retrieve("pedido", top_k=1, mode="lexical", rerank=True)) == 1
    assert seen == [3]
    with pytest.raises(ValueError, match="rerank_pool"):
        RAGPipeline(_CHUNKS, answer_generator=DeterministicAnswerGenerator(), rerank_pool=0)


@pytest.fixture
def dataset(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    queries = tmp_path / "queries.jsonl"
    corpus.write_text("".join(
        json.dumps({"doc_id": c.doc_id, "title": c.title, "text": c.text}) + "\n"
        for c in _CHUNKS
    ), encoding="utf-8")
    cases = [
        {"query_id": "q1", "question": "pedido no portal", "relevant_doc_ids": ["b"],
         "split": "test", "category": "direct"},
        {"query_id": "q2", "question": "reembolso", "relevant_doc_ids": ["a"],
         "split": "test", "category": "direct"},
    ]
    queries.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    return corpus, queries


def test_semantic_benchmark_records_pinned_models(dataset):
    report = run_benchmark(
        *dataset, split="test", backend="sentence-transformer", top_ks=(1,), repeats=1,
        strategies=("vector", "bm25-ce", "rrf-ce"),
        embedder=SentenceTransformerEmbedder(model=FakeEncoder()),
        cross_encoder=CrossEncoderReranker(model=FakeCrossEncoder("portal")),
    )
    env = report.environment
    assert report.embedding_backend == "sentence-transformer"
    assert env["embedding_model"] == DEFAULT_ST_MODEL
    assert env["embedding_revision"] == DEFAULT_ST_REVISION
    assert env["cross_encoder_revision"] == DEFAULT_CE_REVISION
    assert env["embedding_dimensions"] == str(len(FakeEncoder.vocabulary))
    rows = {row.strategy: row for row in report.rows}
    assert rows["bm25-ce"].per_query[0].retrieved_doc_ids == ["b"]
    assert rows["vector"].mean_metrics is not None

    other = report.model_copy(deep=True)
    other.environment["embedding_revision"] = "different"
    with pytest.raises(ValueError, match="embedding_revision"):
        compare_reports(report, other)
    assert compare_reports(report, report) == []


def test_lexical_benchmark_does_not_load_semantic_models(dataset, monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    report = run_benchmark(*dataset, split="test", top_ks=(1,), repeats=1, strategies=("bm25",))
    assert report.environment["cross_encoder_model"] == "not-used"
    assert report.environment["embedding_model"] == "hashing"
    assert report.environment["torch"] == "not-used"
