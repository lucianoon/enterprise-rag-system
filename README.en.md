# Enterprise RAG System

*[Versão em português](README.md)*

[![CI](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/lucianoon/enterprise-rag-system)

**[Live demo](https://enterprise-rag-demo.onrender.com/docs)** — interactive
API with the sample corpus loaded; try `POST /query` and `POST /evaluate/batch`
straight from the browser (free tier: the first request may take ~1 min to
wake the service).

**Measured test evidence:** the CI reports **81% branch coverage** across 633
statements and 128 branches, with a **minimum 80% gate** that blocks material
regressions. The machine-readable `coverage.json` is retained as a workflow
artifact for 14 days.

A retrieval-quality-first RAG engine: hybrid search (BM25-style lexical + vector) with
score fusion, a heuristic rerank pass (title and exact-phrase overlap — not a
cross-encoder), citation-carrying answers, and a built-in evaluation endpoint that
reports **Recall@K** and **MRR** for any labeled query. Every response exposes its
per-stage scores so you can see *why* a chunk was retrieved, not just *that* it was.

**Measured public baseline:** on the `retrieval_v1` demo dataset (10 queries),
the hashing + in-memory configuration reached **Recall@1 = 1.000** and
**MRR = 1.000** on August 2, 2026. The corpus contains only three documents;
read the [results and limitations](docs/BENCHMARK_RESULTS.md) before interpreting
or comparing these numbers.

> **Not the same project as [RAG Agentic System](https://github.com/lucianoon/rag-agentic-system).**
> This engine retrieves **once** and answers; the design goal is a ranked list whose
> quality you can measure. The other one wraps retrieval in a **multi-step Claude
> tool-use loop** where the model decides when to search again. Different problems:
> this repo optimizes ranking quality, that one optimizes multi-step reasoning
> over a corpus.

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
uv sync --extra dev              # core: runs fully offline
uv sync --extra dev --extra extras   # optional: qdrant-client + scikit-learn

uv run pytest -q                 # 55 tests, no network, no API key
uv run ruff check . && uv run mypy   # the same gates CI enforces
uv run uvicorn enterprise_rag_system.api:app --port 8000
```

Versions come from `uv.lock`, so your machine, CI and the Docker image all
resolve the exact same dependencies.

Or with make: `make install && make test && make dev`. Docker:
`docker compose up --build` starts the API wired to a real Qdrant instance
(`RAG_VECTOR_STORE=qdrant`, `RAG_EMBEDDING_BACKEND=tfidf`).

The API boots against the bundled sample corpus (`data/sample/policies.jsonl` — refund,
security and SLA policies), so you can query it immediately.

### Answer generation modes

Set `RAG_LLM_MODE` (see `.env.example`):

- `auto` (default) — call the model when a backend is configured, else the deterministic template
- `llm` — always call the model (see [Swapping model or provider](#swapping-model-or-provider))
- `deterministic` — always use the offline template (what CI runs)

A transient API error falls back to the deterministic answer, so `/query` never
hard-fails (the failure is logged with a full traceback). The active mode is reported
as `generation_mode` in response metadata.

### Swapping model or provider

LLM access goes through a single port (`llm_client.py`) with two backends behind
one interface — the answer generator and the faithfulness judge both use it:

| Variable | Values |
|---|---|
| `RAG_LLM_BACKEND` | `auto` (default), `anthropic`, `openai` |
| `RAG_LLM_MODEL` | model id; defaults to `claude-opus-5` or `gpt-4.1-mini` |
| `RAG_LLM_BASE_URL` | OpenAI-compatible endpoint (also accepts `OPENAI_BASE_URL`) |
| `RAG_LLM_API_KEY` | credential; falls back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |

In `auto` mode: an Anthropic key ⇒ `anthropic`; otherwise a base URL or an
OpenAI key ⇒ `openai`; with neither, the pipeline uses the deterministic
generator.

```bash
# OpenRouter, Groq, Together, DeepInfra, Fireworks…
export RAG_LLM_BASE_URL=https://openrouter.ai/api/v1
export RAG_LLM_API_KEY=sk-or-v1-...
export RAG_LLM_MODEL=meta-llama/llama-3.3-70b-instruct

# Local Ollama — no credential at all
export RAG_LLM_BASE_URL=http://localhost:11434/v1
export RAG_LLM_MODEL=llama3.1
```

The OpenAI-compatible backend ships in the `extras` optional group.

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

### Answer faithfulness

Retrieval metrics stop at the ranked list; `/evaluate/answer` judges what the
*generator* did with it — the fraction of answer claims supported by the retrieved
passages, plus the unsupported claims verbatim:

```bash
curl -X POST http://localhost:8000/evaluate/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "What must a refund request include?", "top_k": 3}'
```

Two judges share one interface, selected by `RAG_JUDGE_MODE` (`answer_eval.py`):

- `heuristic` (default) — per-sentence lexical containment against the context.
  Deterministic and offline: a cheap proxy for groundedness that CI can gate on, not
  a semantic entailment check.
- `llm` — Claude scores faithfulness and lists unsupported claims
  (`RAG_JUDGE_MODEL` overrides the model). Falls back to the heuristic judge on API
  errors, reported as `judge_mode: "heuristic-fallback"`.

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
| `/evaluate/answer` | POST | `{question, top_k}` → answers the question, then judges the answer's faithfulness against its own retrieved context |

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

## Quality and contributing

Changes to retrieval, chunking, score fusion, or reranking should include a
reproducible comparison. The [benchmark protocol](docs/BENCHMARKING.md) defines
the dataset, commands, metrics, and report format without publishing results
that were not actually measured.

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md); issue
templates collect environment and reproduction details, while the pull request
template requires the same CI gates and regression evidence for retrieval
changes.

## Roadmap

- Cross-encoder reranker
- Batch answer-quality evaluation (aggregate faithfulness over the eval dataset)
- Incremental indexing instead of full reindex on startup

## License

[MIT](LICENSE) — © 2026 Luciano de Oliveira Nunes.
