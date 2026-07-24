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
| Embeddings | `embeddings.py` | Pluggable backends: deterministic hashing (offline/CI default), TF-IDF (scikit-learn) or dense semantic vectors (sentence-transformers) |
| Vector store | `vector_store.py` | Pluggable backends: exact in-memory cosine search or a real Qdrant index (the one `docker compose` starts) |
| Score fusion | `retrieval.py` | Weighted hybrid score: `0.55 * lexical + 0.45 * vector` |
| Reranking | `retrieval.py` | Boosts results by query/title token overlap plus an exact-title-phrase bonus |
| Generation | `generation.py` | Claude synthesizes a grounded answer with bracketed citations; a deterministic template generator is the offline/CI fallback |
| Citations | `pipeline.py` | Every answer ships with `doc_id` / `title` / `chunk_id` for each supporting chunk |
| Evaluation | `evaluation.py` | Recall@K and MRR per labeled query, plus batch evaluation over a versioned dataset with aggregate metrics |
| API | `api.py` | FastAPI service: `/health`, `/query`, `/evaluate`, `/evaluate/batch`, optional API-key auth |

The retrieval *interfaces* (chunks in, `SearchResult` with `lexical_score` /
`vector_score` / `hybrid_score` / `rerank_score` out) are the point: the same pipeline
runs against the zero-dependency offline backends or against Qdrant + real embeddings,
selected purely by environment variables.

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
Lexical index (IDF)    Embedder -> Vector store
                       (hashing|tfidf|st)  (memory|qdrant)
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
pip install -r requirements.txt            # core: runs fully offline
pip install -r requirements-extras.txt     # optional: qdrant-client + scikit-learn

pytest -q                      # 29 tests, no network, no API key
uvicorn enterprise_rag_system.api:app --app-dir src --port 8000
```

Or with make: `make install && make test && make dev`. Docker:
`docker compose up --build` starts the API wired to a real Qdrant instance
(`RAG_VECTOR_STORE=qdrant`, `RAG_EMBEDDING_BACKEND=tfidf`).

The API boots against the bundled sample corpus (`data/sample/policies.jsonl` — refund,
security and SLA policies), so you can query it immediately.

### Answer generation modes

Set `RAG_LLM_MODE` (see `.env.example`):

- `auto` (default) — use Claude when `ANTHROPIC_API_KEY` is set, else the deterministic template
- `llm` — always call Claude (`RAG_LLM_MODEL` overrides the model id)
- `deterministic` — always use the offline template (what CI runs)

A transient Claude API error falls back to the deterministic answer, so `/query` never
hard-fails (the failure is logged with a full traceback). The active mode is reported
as `generation_mode` in response metadata.

### Retrieval backends

Both retrieval stages are selected by environment variables (see `.env.example`):

- `RAG_EMBEDDING_BACKEND` — `hashing` (default: deterministic, zero dependencies,
  stable across processes), `tfidf` (scikit-learn, fitted on the indexed corpus),
  `sentence-transformer` (dense semantic vectors, heavy) or `auto` (best available).
- `RAG_VECTOR_STORE` — `memory` (default: exact in-process cosine search) or `qdrant`
  (uses `QDRANT_URL` and `COLLECTION_NAME`; `docker compose` wires this up).
- `RAG_API_KEY` — when set, `/query` and `/evaluate*` require the same value in the
  `X-API-Key` header. Unset means open access for local development.

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

### Batch evaluation over a versioned dataset

A labeled dataset ships with the repo (`data/eval/retrieval_v1.jsonl` — 10 queries
against the sample corpus). Run it through the API or the CLI:

```bash
curl -X POST http://localhost:8000/evaluate/batch \
  -H "Content-Type: application/json" -d '{"top_k": 3}'

python -m enterprise_rag_system.evaluation --top-k 1     # or: make eval
```

The report contains `mean_recall_at_k`, `mean_mrr` and per-query metrics, so a change
to fusion weights, chunking or the reranker shows up as a measurable diff instead of a
vibe. Point `RAG_EVAL_DATASET` at your own JSONL
(`{"query_id", "question", "relevant_doc_ids"}` per line) to evaluate a real corpus.

### Retrieval trade-offs made explicit

- **Fusion weights** (`0.55` lexical / `0.45` vector) favor exact enterprise terminology
  slightly over paraphrase matching — tune per corpus and re-check MRR.
- **Candidate pool**: the pipeline retrieves `2 * top_k` candidates before reranking, a
  recall-vs-latency knob.
- **Default hashed embeddings** trade semantic quality for determinism and zero
  infrastructure — ideal for CI and for isolating lexical-vs-vector behavior; the
  `tfidf` and `sentence-transformer` backends provide production semantics behind the
  same interface.
- **Reranker** is a cheap heuristic (title overlap + exact phrase), not a cross-encoder;
  it improves precision on title-shaped queries without adding a model dependency.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check (always open) |
| `/query` | POST | `{question, top_k}` → grounded answer, citations, per-stage scores, latency metadata |
| `/evaluate` | POST | `{question, relevant_doc_ids, top_k}` → Recall@K, MRR, retrieved IDs, full query response |
| `/evaluate/batch` | POST | `{top_k}` → aggregate Recall@K / MRR over the versioned eval dataset |

When `RAG_API_KEY` is set, all endpoints except `/health` require the `X-API-Key`
header.

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

Tests cover the API endpoints (including auth and validation errors), retrieval units,
every embedding and vector store backend (Qdrant runs in `:memory:` mode), batch
evaluation, and generator selection/fallback behavior. They run entirely offline — the
deterministic embedding and generator paths mean CI needs no secrets, which is exactly
how [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs them.

## Roadmap

- Cross-encoder reranker
- Answer-quality evaluation (faithfulness/groundedness) on top of retrieval metrics
- Incremental indexing instead of full reindex on startup

## License

[MIT](LICENSE) — © 2026 Luciano de Oliveira Nunes.
