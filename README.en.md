# Enterprise RAG System

*[Versão em português](README.md)*

[![CI](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/lucianoon/enterprise-rag-system)

A RAG engine where **retrieval quality is the product**, measured in
Portuguese. Most RAG failures are retrieval failures: semantic search misses
exact terms (policy names, acronyms, IDs), keyword search misses paraphrases,
and without metrics you cannot tell whether a bad answer came from the
generator or from the ranked list. This repository treats that as measurable
engineering:

- **BM25 with Unicode normalization** (NFKD, accents removed, casefold) in a
  single analyzer shared by every pipeline;
- **pluggable vectors**: deterministic hashing (CI), TF-IDF or **real
  multilingual embeddings** (`multilingual-e5-small`, CPU, pinned revision);
- **score fusion or RRF**, plus heuristic reranking or an optional
  **multilingual cross-encoder**;
- citation-carrying answers, per-stage scores and an evaluation endpoint;
- **regression gates in CI**: a versioned Portuguese benchmark with SHA-256 data
  hashes, frozen baselines and zero tolerance.

## Measured results

`corporate_pt_v1`, **test** split: 30 fictional documents, 35 answerable and 5
unanswerable questions, no LLM involved. Measured on 2026-09-22 (CPU,
Windows 11, Python 3.12).

| Configuration | Recall@1 | Recall@5 | MRR@5 | nDCG@5 | p95@5 |
|---|---:|---:|---:|---:|---:|
| Hybrid + reranker, hashing (API default) | 0.571 | 0.886 | 0.760 | 0.781 | < 1 ms |
| Legacy lexical | 0.686 | 0.914 | 0.824 | 0.834 | < 1 ms |
| BM25 | 0.743 | 0.943 | 0.867 | 0.873 | < 1 ms |
| RRF: BM25 + TF-IDF | 0.700 | 0.943 | 0.846 | 0.855 | ~3 ms |
| `multilingual-e5-small` vector | 0.757 | **0.971** | 0.891 | 0.911 | ~56 ms |
| **RRF: BM25 + e5** | **0.843** | **0.971** | **0.943** | 0.945 | ~49 ms |
| BM25 + mMiniLM cross-encoder | 0.843 | 0.971 | 0.943 | **0.950** | ~1.6 s |

- A real multilingual embedding **beats lexical retrieval** on this set (the
  previous best was legacy lexical at Recall@5 = 0.957); RRF is the fusion that
  keeps the gain. The cross-encoder ties RRF + e5 at ~30x the latency.
- The API default stays `hybrid` + hashing, with no heavy dependencies; changing
  it requires a new, independent test set.
- Synthetic, AI-assisted corpus and an already-known test split: these numbers
  **do not establish superiority on real data**. Details, dev split and
  limitations: [multilingual embeddings](docs/MULTILINGUAL_RETRIEVAL_RESULTS.md),
  [BM25/RRF](docs/BM25_RRF_RESULTS.md),
  [baseline and analyzer unification](docs/CORPORATE_BENCHMARK_RESULTS.md),
  [protocol](docs/BENCHMARKING.md) (Portuguese).

```bash
uv run python -m enterprise_rag_system.benchmark --split test \
  --baseline data/benchmarks/corporate_pt_v1/baseline-hashing-test.json
# multilingual embeddings (optional extra, ~0.5 GB download):
uv sync --extra dev --extra extras --extra semantic
uv run python -m enterprise_rag_system.benchmark --split test \
  --backend sentence-transformer --strategies bm25 vector rrf
```

**[Live demo](https://enterprise-rag-demo.onrender.com/docs)** — interactive
API with the sample corpus loaded; try `POST /query` and `POST /evaluate/batch`
straight from the browser (free tier: the first request may take ~1 min to
wake the service).

**Measured test evidence:** CI enforces a **minimum 80% combined line/branch
coverage gate** and frozen retrieval quality baselines. The machine-readable
`coverage.json` is retained as a workflow artifact for 14 days.

## Quick evidence

| Evidence | What it demonstrates |
|---|---|
| Offline tests in CI | API, auth, retrieval, backends, concurrency and evaluation |
| Statement and branch coverage, gate ≥ 80% | Automated coverage checks |
| 30 documents and 80 synthetic Portuguese queries | Retrieval baseline with dev/test splits |
| Lexical/vector/hybrid matrix and quality gate | Reproducible Recall, MRR, nDCG, precision and latency |
| Per-stage scores | Diagnosing retrieval failures |
| Hashing/TF-IDF/multilingual e5 + cross-encoder | Deterministic CI plus a real semantic backend with pinned model revisions |
| In-memory/Qdrant | Same interface from local tests to external infrastructure |
| Heuristic or LLM judge | Faithfulness evaluation with an explicit fallback |

See also the [product direction](docs/PRODUCT_DIRECTION.md).

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
| Text analysis | `tokenization.py` | One analyzer (NFKD, accent removal, casefold) for lexical, BM25, vectors, reranker, judge and product |
| Lexical retrieval | `retrieval.py`, `ranking.py` | Legacy IDF/log-TF score and full BM25 (`k1=1.2`, `b=0.75`) over posting lists |
| Embeddings | `embeddings.py` | Pluggable backends: deterministic hashing (offline/CI default), TF-IDF (scikit-learn) or dense multilingual vectors (pinned `multilingual-e5-small`, `semantic` extra) |
| Vector store | `vector_store.py` | Pluggable backends: exact in-memory cosine search or a real Qdrant index (the one `docker compose` starts) |
| Fusion | `retrieval.py`, `ranking.py` | Weighted hybrid score `0.55 * lexical + 0.45 * vector` or Reciprocal Rank Fusion |
| Reranking | `retrieval.py`, `cross_encoder.py` | Title heuristic (overlap + exact phrase) or an optional multilingual cross-encoder over a candidate pool |
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

uv run pytest -q                 # offline tests, no API key
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

## Usage examples

### Persistent product pilot

`docker compose -f compose.product.yml up --build -d` starts an explicit mode,
separate from the demo API: a Portuguese document library, revisions, restore,
tenant/document permissions applied before retrieval, revocable credentials and
source-backed queries. The product BM25 index reuses the core and is cached per
authorized snapshot, invalidated on every edit. See the
[provisioning, permissions and backup guide](docs/PRODUCT_PILOT.md) (Portuguese).

### Configurable editorial profile

The pilot accepts versioned prompt profiles (`RAG_PRODUCT_PROFILE`), with the
prompt hash in every response's metadata. One bundled example is a study
assistant inspired by a pastor's public themes, which always presents itself as
an AI assistant rather than the person:
[configuration and sources](docs/PASTORAL_PROFILE.md) (Portuguese).

## Configuration

### Answer generation modes

Set `RAG_LLM_MODE` (see `.env.example`):

- `auto` (default) — call the model when a backend is configured, else the deterministic template
- `llm` — always call the model (see [Swapping model or provider](#swapping-model-or-provider))
- `deterministic` — always use the offline template (what CI runs)

LLM failures, empty responses, refusals and filtered responses trigger the
deterministic fallback and are logged. `generation_mode` reports the path
actually used for that response: `llm` for model-generated text,
`deterministic-fallback` after an LLM failure, and `deterministic` for the
offline template or a response without context. This state belongs to each
request, including when queries run concurrently.

The Python interface `compose(question, results)` still returns text.
Generators whose mode varies per request can implement
`compose_with_metadata(question, results)`, returning `GeneratedAnswer(text, mode)`.
Existing custom generators with `compose` and `mode` remain supported.

### Swapping model or provider

LLM access goes through a single port (`llm_client.py`) with two backends behind
one interface — the answer generator and the faithfulness judge both use it:

| Variable | Values |
|---|---|
| `RAG_LLM_BACKEND` | `auto` (default), `anthropic`, `openai` |
| `RAG_LLM_MODEL` | model id; defaults to `claude-opus-5` or `gpt-4.1-mini` |
| `RAG_LLM_BASE_URL` | OpenAI-compatible endpoint (also accepts `OPENAI_BASE_URL`) |
| `RAG_LLM_API_KEY` | credential; falls back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |

In `auto` mode, a base URL selects `openai`, even when an Anthropic key is also
exported. Without a URL, an Anthropic key takes precedence over an OpenAI key.
The generic `RAG_LLM_API_KEY` overrides the selected provider's credential;
when configured alone, it retains the `anthropic` default for compatibility.
With no configuration, the pipeline uses the deterministic generator.
`RAG_LLM_BACKEND=anthropic` or `openai` always overrides automatic selection;
set it explicitly to keep Anthropic when an OpenAI-compatible URL is present
in the environment.

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
  `sentence-transformer` (dense multilingual vectors; defaults to
  `intfloat/multilingual-e5-small` at a pinned revision, overridable with
  `RAG_ST_MODEL`/`RAG_ST_REVISION`; requires `--extra semantic`) or `auto` (best available).
- `RAG_VECTOR_STORE` — `memory` (default: exact in-process cosine search) or `qdrant`
  (uses `QDRANT_URL` and `COLLECTION_NAME`; `docker compose` wires this up).
- `RAG_API_KEY` — when set, `/query` and `/evaluate*` require the same value in the
  `X-API-Key` header. Unset means open access for local development.

### Custom corpus and retained index generations

Set `RAG_DOCUMENTS_PATH` to a JSONL file with `doc_id`, `title`, and `text` per line.
IDs must be unique and fields nonblank. Invalid input fails startup before index
construction; leaving the variable unset retains the demo corpus. Configure
`RAG_EVAL_DATASET` with labels for your corpus when using batch evaluation.

Qdrant builds a new physical generation and activates it only after completed
batch writes and exact count validation. Existing collections are retained.
`COLLECTION_NAME` is a namespace prefix rather than a shared active alias.
**Retained generations require storage monitoring and operator-managed cleanup.**
This does not add incremental ingestion, tenant isolation or restart reuse.
See the [research, operational contract and limitations](docs/SAFE_INGESTION_STRATEGY.md).

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
- **The default reranker** is a cheap heuristic (title overlap + exact phrase). The
  optional multilingual cross-encoder
  (`RAGPipeline(chunks, reranker=CrossEncoderReranker(), rerank_pool=20)`) did not
  improve Recall/MRR over RRF + e5 on the benchmark and costs ~1.6 s per query on CPU.

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

- Light Portuguese stemming (RSLP), evaluated on dev
- An independent test set to decide RRF + e5 as the default
- Batch answer-quality evaluation (aggregate faithfulness over the eval dataset)
- Incremental indexing instead of full reindex on startup

## License

[MIT](LICENSE) — © 2026 Luciano de Oliveira Nunes.
