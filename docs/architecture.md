# Architecture

## Query Flow

1. Documents are loaded from a source and split into chunks.
2. The lexical index scores chunks by token overlap and inverse document frequency.
3. The vector index uses deterministic local embeddings for offline execution.
4. The hybrid retriever combines lexical and vector scores.
5. The reranker boosts exact phrase and title matches.
6. The answer composer returns a grounded response with citations.
7. The evaluator computes Recall@K and MRR when labels are provided.

## Production Boundary

The current implementation is intentionally local and deterministic. Production adapters would include:

- Qdrant collection manager
- managed embedding provider
- document registry database
- async ingestion jobs
- OpenTelemetry traces
- feedback capture
- tenant isolation

## Design Principles

- Retrieval should be measurable.
- Citations are part of the answer contract.
- Lexical search remains useful for exact terms.
- Vector search should be swappable.
- Evaluation should run in CI.


## Index generations and startup

The API loads `RAG_DOCUMENTS_PATH` or the bundled sample JSONL and validates
nonempty unique records before backend initialization. Qdrant indexes each
replacement into a fresh physical collection; completed writes and exact point
count must succeed before the adapter switches its local active generation.
Existing collections remain untouched. Readers pin to their generation because
chunk text and lexical state remain process-local.

This is not hot reload: construct a new pipeline with its own adapter when
loading a different corpus. Startup still rebuilds the index, and generations
are retained without automatic cleanup or a durable reader registry. These
limits and the reasoning against a shared mutable alias are documented in
[the ingestion strategy](SAFE_INGESTION_STRATEGY.md).
