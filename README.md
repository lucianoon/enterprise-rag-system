# Enterprise RAG System

Hybrid retrieval system with citations, reranking, evaluation and observability for enterprise knowledge bases.

This project is a portfolio-grade AI Engineering system: it demonstrates the core pieces needed to move from "chat with docs" demos to reliable retrieval-augmented generation workflows.

## Problem

Enterprise users need answers grounded in internal documents, but naive semantic search often fails on exact terms, IDs, policies and compliance language. Production RAG needs hybrid retrieval, citations, evaluation, latency tracking and transparent trade-offs.

## Solution

Enterprise RAG System implements a deterministic, testable RAG pipeline:

- Document ingestion and chunking
- BM25-style lexical retrieval
- Deterministic vector retrieval
- Hybrid score fusion
- Reranking
- Citation-aware answer generation with Claude (deterministic fallback for CI)
- Recall@K and MRR evaluation
- API surface for query and evaluation

## Architecture

```text
Documents
  |
  v
Ingestion + Chunking
  |
  v
Lexical Index + Vector Index
  |
  v
Hybrid Retriever
  |
  v
Reranker
  |
  v
Answer Composer + Citations
  |
  v
Evaluation + Observability
```

See [docs/architecture.md](docs/architecture.md).

## Tech Stack

- Python
- FastAPI
- Pydantic
- BM25-style retrieval
- Deterministic local embeddings
- Claude (Anthropic SDK) for grounded answer generation
- Qdrant-ready vector adapter boundary
- Docker Compose
- pytest

## Repository Structure

```text
.
├── data/sample/
├── docs/
├── src/enterprise_rag_system/
├── tests/
├── docker/
├── docker-compose.yml
├── .env.example
├── Makefile
├── architecture.png
├── CHANGELOG.md
└── README.md
```

## How To Run

```bash
cp .env.example .env
make install
make test
make dev
```

## API Examples

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the refund policy require?","top_k":3}'
```

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the refund policy require?","relevant_doc_ids":["policy_refunds"]}'
```

## Answer Generation

Retrieved passages are handed to a pluggable answer generator:

- **`llm`** — Claude (via the Anthropic SDK) synthesizes a grounded answer with
  bracketed citations over the numbered passages. Set `ANTHROPIC_API_KEY` (or an
  `ant auth login` profile) and the model with `RAG_LLM_MODEL` (default
  `claude-opus-4-8`).
- **`deterministic`** — a template answer from the top chunk. No network access,
  so demos, tests and CI stay reproducible.

`RAG_LLM_MODE` selects the strategy: `auto` (default — Claude when a key is
present, otherwise deterministic), `llm`, or `deterministic`. Every response
reports the active `generation_mode` in its metadata, and a transient API error
transparently falls back to the deterministic answer so a query never hard-fails.

## Evaluation

The evaluation layer measures:

- Recall@K
- MRR
- Citation coverage
- Answer groundedness
- Retrieval latency
- Empty-result risk

## Observability

Every query returns:

- query id
- latency
- retrieved chunks
- score components
- citations
- evaluation metadata when requested

## Trade-Offs

Retrieval uses deterministic, local embeddings so the system can run in CI
without API keys, while answer generation calls Claude when a key is present and
otherwise falls back to a deterministic template. The interfaces are shaped so
Qdrant embeddings or a different LLM can be swapped in without changing the API
contract.

## Roadmap

- [ ] Qdrant adapter
- [ ] PostgreSQL document registry
- [ ] Real embedding adapter (Voyage / local model)
- [ ] Cross-encoder reranker
- [ ] Langfuse traces
- [ ] Prometheus metrics
- [ ] Multi-tenant collections
- [ ] Incremental indexing

