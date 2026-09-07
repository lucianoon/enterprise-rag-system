# Architecture

## Persistent pilot mode

`RAG_PRODUCT_DB` selects `product_api` instead of the legacy pipeline below.
The SQLite registry authenticates a token and reads a tenant/document ACL
snapshot in one transaction. Only authorized content reaches chunking, BM25
and optional generation. Writes atomically append document versions, update
heads and corpus revision, and record audit metadata. No Qdrant collection is
created on startup. The browser stores tokens in memory and renders content
as text. See [contracts and operational limits](PRODUCT_PILOT.md).

## Legacy engine query flow

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
- integration of vector generations with the persistent document registry
- async ingestion jobs
- OpenTelemetry traces
- feedback capture
- SSO and operational hardening beyond the pilot ACL model

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
