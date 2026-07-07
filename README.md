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
- Citation-aware answer composition
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

The default vector implementation is deterministic and local so the system can run in CI without API keys. The interface is shaped so Qdrant/OpenAI embeddings can be added without changing the API contract.

## Roadmap

- [ ] Qdrant adapter
- [ ] PostgreSQL document registry
- [ ] OpenAI or local embedding adapter
- [ ] Cross-encoder reranker
- [ ] Langfuse traces
- [ ] Prometheus metrics
- [ ] Multi-tenant collections
- [ ] Incremental indexing

