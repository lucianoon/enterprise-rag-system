# Enterprise RAG System

[![CI](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A retrieval-quality-first RAG engine: hybrid search (BM25-style lexical + vector) with
score fusion, a rerank pass, citation-carrying answers, and a built-in evaluation
endpoint that reports **Recall@K** and **MRR** for any labeled query. Every response
exposes its per-stage scores so you can see *why* a chunk was retrieved, not just *that*
it was.

## Problem

Most RAG failures are retrieval failures. Pure semantic search misses exact terms that
dominate enterprise queries — policy names, IDs, acronyms, compliance language — while
pure keyword search misses paraphrases. And without retrieval metrics, you cannot tell
whether a bad answer came from the generator or from the ranked list it was given.

This project treats retrieval as the measurable core of the system:

- fuse lexical and vector evidence instead of betting on one signal
- keep score components transparent end to end
- make Recall@K / MRR evaluation a first-class API operation, not an afterthought

## Solution

A compact, fully typed pipeline (`src/enterprise_rag_system/`):

| Stage | Module | What it actually does |
|---|---|---|
| Ingestion | `ingestion.py` | Loads JSONL documents, splits them into fixed-size word-count chunks (default 80 words) |
| Lexical retrieval | `retrieval.py` | BM25-style scoring: IDF-weighted term matching with log-scaled term frequency |
| Vector retrieval | `retrieval.py` | Deterministic local hashed bag-of-words embeddings (48 dims, cosine similarity) — runs offline, no model download, no API key |
| Score fusion | `retrieval.py` | Weighted hybrid score: `0.55 * lexical + 0.45 * vector` |
| Reranking | `retrieval.py` | Boosts results by query/title token overlap plus an exact-title-phrase bonus |
| Generation | `generation.py` | Claude synthesizes a grounded answer with bracketed citations; a deterministic template generator is the offline/CI fallback |
| Citations | `pipeline.py` | Every answer ships with `doc_id` / `title` / `chunk_id` for each supporting chunk |
| Evaluation | `evaluation.py` | Recall@K and MRR against labeled relevant document IDs |
| API | `api.py` | FastAPI service: `/health`, `/query`, `/evaluate` |

The vector stage intentionally uses cheap deterministic embeddings: the retrieval
*interfaces* (chunks in, `SearchResult` with `lexical_score` / `vector_score` /
`hybrid_score` / `rerank_score` out) are the point, and they stay stable when you swap
in a real embedding model or vector store.

## Architecture

![Architecture](architecture.png)

```text
JSONL documents
      |
      v
Ingestion -> word-count chunks
      |
      +----------------------+
      |                      |
      v                      v
Lexical index (IDF)    Vector index (hashed embeddings)
      |                      |
      +----- score fusion ---+
      |   0.55*lex + 0.45*vec
      v
Reranker (title overlap + exact-phrase bonus)
      |
      v
Answer generator (Claude, deterministic fallback) + citations
      |
      v
Evaluator (Recall@K, MRR)  <- labeled queries via /evaluate
```

More detail in [docs/architecture.md](docs/architecture.md).

## Quickstart

Requires Python 3.12+.

```bash
git clone https://github.com/lucianoon/enterprise-rag-system.git
cd enterprise-rag-system
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                      # 8 tests, no network, no API key
uvicorn enterprise_rag_system.api:app --app-dir src --port 8000
```

Or with make: `make install && make test && make dev`. Docker: `docker compose up --build`.

The API boots against the bundled sample corpus (`data/sample/policies.jsonl` — refund,
security and SLA policies), so you can query it immediately.

### Answer generation modes

Set `RAG_LLM_MODE` (see `.env.example`):

- `auto` (default) — use Claude when `ANTHROPIC_API_KEY` is set, else the deterministic template
- `llm` — always call Claude (`RAG_LLM_MODEL` overrides the model id)
- `deterministic` — always use the offline template (what CI runs)

A transient Claude API error falls back to the deterministic answer, so `/query` never
hard-fails. The active mode is reported as `generation_mode` in response metadata.

## Evaluation: Recall@K and MRR

Retrieval quality is evaluated per labeled query through the API (or
`RetrievalEvaluator` in code):

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
        "question": "What is the SLA for high priority support tickets?",
        "relevant_doc_ids": ["policy_sla"],
        "top_k": 3
      }'
```

Response (excerpt):

```json
{
  "recall_at_k": 1.0,
  "mrr": 1.0,
  "retrieved_doc_ids": ["policy_sla", "policy_refunds", "policy_security"],
  "query": { "answer": "...", "citations": [...], "results": [...] }
}
```

How to read the numbers:

- **Recall@K** — fraction of the labeled relevant documents that appear anywhere in the
  top-K citations. `1.0` means everything relevant was retrieved; low recall means the
  retriever (not the generator) is the bottleneck.
- **MRR** — reciprocal rank of the *first* relevant hit. `1.0` = relevant doc ranked
  first, `0.5` = second, `0.33` = third, `0.0` = missed entirely. High recall with low
  MRR points at ranking/fusion weights or the reranker, not at candidate generation.

Each `SearchResult` also returns its `lexical_score`, `vector_score`, `hybrid_score`
and `rerank_score`, so you can trace a bad ranking to the exact stage that caused it.

### Retrieval trade-offs made explicit

- **Fusion weights** (`0.55` lexical / `0.45` vector) favor exact enterprise terminology
  slightly over paraphrase matching — tune per corpus and re-check MRR.
- **Candidate pool**: the pipeline retrieves `2 * top_k` candidates before reranking, a
  recall-vs-latency knob.
- **Hashed embeddings** trade semantic quality for determinism and zero infrastructure —
  ideal for CI and for isolating lexical-vs-vector behavior; swap in real embeddings
  behind the same interface for production semantics.
- **Reranker** is a cheap heuristic (title overlap + exact phrase), not a cross-encoder;
  it improves precision on title-shaped queries without adding a model dependency.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check |
| `/query` | POST | `{question, top_k}` → grounded answer, citations, per-stage scores, latency metadata |
| `/evaluate` | POST | `{question, relevant_doc_ids, top_k}` → Recall@K, MRR, retrieved IDs, full query response |

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the refund policy require?","top_k":3}'
```

Response metadata includes `query_id`, `latency_ms`, `top_k`, `result_count` and
`generation_mode`. All request/response contracts are Pydantic models in
[`models.py`](src/enterprise_rag_system/models.py).

## Tests

```bash
pytest -q
```

Tests cover the API endpoints, the pipeline (citations + Recall/MRR on the sample
corpus), and generator selection/fallback behavior. They run entirely offline — the
deterministic embedding and generator paths mean CI needs no secrets, which is exactly
how [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs them.

## Roadmap

- Real embedding adapter and vector store (interfaces already isolate this)
- Cross-encoder reranker
- Batch evaluation over a query set with aggregate Recall@K / MRR

## License

[MIT](LICENSE) — © 2026 Luciano de Oliveira Nunes.
